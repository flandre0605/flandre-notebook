"""Fault and cross-device checks using temporary data and synthetic credentials only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QImage
from app.database import store
from app.services import attachments, backup, model_provider, question_files
from scripts import build_android


class ReliabilityChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='flandre-reliability-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / 'questions.db'
        store.initialize(self.database)
        connection = store._connection
        for target, name, value in (
            (store, '_connection', lambda path=None: connection(path or self.database)),
            (store, 'DATA_DIR', self.root), (store, 'DATABASE_PATH', self.database),
            (attachments, 'ATTACHMENTS_DIR', self.root / 'attachments'),
            (backup, 'ATTACHMENTS_DIR', self.root / 'attachments'),
        ):
            replacement = patch.object(target, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.image = self.root / 'paper.png'
        image = QImage(64, 64, QImage.Format.Format_RGB32)
        image.fill(0xffabcdef)
        assert image.save(str(self.image))

    def test_backup_keeps_previous_file_on_write_and_replace_failure(self):
        attachments.import_recognized_questions([{'stem': 'one'}], self.image)
        destination = backup.create_backup(self.root / 'snapshot.zip')
        previous = destination.read_bytes()
        original = zipfile.ZipFile.write

        def fail_image(archive, filename, arcname=None, *args, **kwargs):
            if arcname.startswith('attachments/'):
                raise OSError('synthetic image write failure')
            return original(archive, filename, arcname, *args, **kwargs)

        for failure in (patch.object(zipfile.ZipFile, 'write', fail_image),
                        patch.object(backup.os, 'replace', side_effect=OSError('synthetic destination failure'))):
            with failure, self.assertRaises(OSError):
                backup.create_backup(destination)
            self.assertEqual(previous, destination.read_bytes())
            self.assertFalse(list(self.root.glob('.flandre-backup-*')))
        original_db = self.database.read_bytes()
        for invalid in (self.database, self.root / 'attachments/snapshot.zip'):
            with self.assertRaises(ValueError):
                backup.create_backup(invalid)
        self.assertEqual(original_db, self.database.read_bytes())
        backup.create_backup(destination)
        with zipfile.ZipFile(destination) as archive:
            self.assertIn('manifest.json', archive.namelist())
            self.assertTrue(any(name.startswith('attachments/') for name in archive.namelist()))

    def test_shared_image_survives_partial_deletion_and_backup_restore(self):
        ids = attachments.import_recognized_questions([{'stem': f'question {i}'} for i in range(3)], self.image)
        rows = [store.list_attachments(qid)[0] for qid in ids]
        self.assertEqual(1, len({row['relative_path'] for row in rows}))
        self.assertEqual(1, len(list(attachments.ATTACHMENTS_DIR.iterdir())))
        image = attachments.attachment_file(rows[0]['relative_path'])
        snapshot = backup.create_backup(self.root / 'shared.zip')
        attachments.delete_image(rows[0]['id'])
        self.assertTrue(image.is_file())
        attachments.delete_question_images(ids[1])
        self.assertTrue(image.is_file())
        attachments.delete_question_images(ids[2])
        self.assertFalse(image.exists())
        backup.restore_backup(snapshot)
        self.assertTrue(image.is_file())
        for qid in ids:
            self.assertEqual(image, attachments.attachment_file(store.list_attachments(qid)[0]['relative_path']))

    def test_failed_batch_removes_only_its_new_copies(self):
        attachments.import_recognized_questions([{'stem': 'kept'}], self.image)
        previous = set(attachments.ATTACHMENTS_DIR.iterdir())
        with patch.object(store, 'save_recognized_questions', side_effect=sqlite3.OperationalError('synthetic commit failure')):
            with self.assertRaises(sqlite3.OperationalError):
                attachments.import_recognized_questions([{'stem': 'discarded'}], self.image)
        self.assertEqual(previous, set(attachments.ATTACHMENTS_DIR.iterdir()))
        self.assertEqual(1, len(store.list_questions()))

    def test_portable_files_and_legacy_phone_json(self):
        fixtures = Path(__file__).parent / 'fixtures'
        expected = question_files.read_questions(fixtures / 'portable_exchange.json')
        self.assertEqual(expected, question_files.read_questions(fixtures / 'portable_exchange.csv'))
        legacy = self.root / 'legacy-phone.json'
        legacy.write_text(json.dumps({'questions': expected}, ensure_ascii=False), encoding='utf-8')
        self.assertEqual(expected, question_files.read_questions(legacy))
        for invalid in ({'format': 'other', 'version': 1, 'questions': expected},
                        {'format': 'flandre-questions', 'version': 2, 'questions': expected}):
            legacy.write_text(json.dumps(invalid), encoding='utf-8')
            with self.assertRaises(ValueError):
                question_files.read_questions(legacy)

    def test_signing_key_survives_clean_build_and_never_changes_automatically(self):
        legacy = self.root / 'build/android-preview-debug.keystore'
        legacy.parent.mkdir()
        legacy.write_bytes(b'synthetic-key')
        with patch.object(build_android, 'ROOT', self.root), patch.dict(os.environ, LOCALAPPDATA=str(self.root / 'local')):
            with patch.object(build_android.shutil, 'copy2', side_effect=OSError('synthetic copy failure')):
                with self.assertRaises(OSError):
                    build_android.signing_key()
            self.assertEqual(b'synthetic-key', legacy.read_bytes())
            self.assertFalse(list((self.root / 'local/FlandreNotebook/signing').iterdir()))
            key = build_android.signing_key()
            self.assertEqual(legacy.read_bytes(), key.read_bytes())
            legacy.unlink()
            self.assertEqual(key, build_android.signing_key())
            key.unlink()
            with self.assertRaises(RuntimeError):
                build_android.signing_key()
            self.assertFalse(key.exists())

    def test_model_redirects_never_forward_credentials(self):
        received = []

        class Target(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(self.headers.get('Authorization'))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"data":[{"id":"synthetic-model"}]}')

            do_POST = do_GET

            def log_message(self, *args):
                pass

        target = ThreadingHTTPServer(('127.0.0.1', 0), Target)

        class Origin(Target):
            def do_GET(self):
                code = int(self.path.split('/')[1])
                self.send_response(code)
                if code != 200:
                    self.send_header('Location', f'http://localhost:{target.server_port}/target')
                self.end_headers()
                if code == 200:
                    self.wfile.write(b'{"data":[{"id":"synthetic-model"}],"choices":[{"message":{"content":"OK"}}]}')

            do_POST = do_GET

        origin = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
        for server in (origin, target):
            Thread(target=server.serve_forever, daemon=True).start()
        try:
            profile = dict(name='synthetic', base_url='', endpoint_path='/chat/completions',
                           model_id='synthetic', timeout_seconds=5, api_key_ref='synthetic')
            with patch.object(model_provider, 'get_api_key', return_value='synthetic-key'):
                for code in (200, 301, 302, 303, 307, 308):
                    profile['base_url'] = f'http://127.0.0.1:{origin.server_port}/{code}'
                    for request in (lambda: model_provider.list_models(profile), lambda: model_provider._request(profile, [])):
                        if code == 200:
                            self.assertTrue(request())
                        else:
                            with self.assertRaisesRegex(model_provider.ProviderError, '未转发 API Key'):
                                request()
            self.assertEqual([], received)
        finally:
            for server in (origin, target):
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    unittest.main()
