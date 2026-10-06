"""Temporary-workspace protocol and fault checks; no personal data or live cloud calls."""
from contextlib import closing, contextmanager
import copy
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QImage
from app.database import store
from app.services import attachments, backup
from app.services.cloud_sync import CloudClient, CloudSession, CloudSyncError, ENVIRONMENT_ID, synchronize
from app.services.cloud_sync_store import SyncStore, dump
from app.services.cloud_accounts import account_directory


class Backend:
    def __init__(self):
        self.rows, self.operations, self.sequences, self.images = {}, {}, {}, {}

    def rpc(self, user, name, arguments):
        if name == 'flandre_sync_pull':
            rows = sorted((copy.deepcopy(row) for row in self.rows.values() if row['user_id'] == user and row['seq'] > arguments['p_after']),
                          key=lambda row: row['seq'])[:arguments['p_limit']]
            return {'records': rows, 'cursor': rows[-1]['seq'] if rows else arguments['p_after']}
        op = (user, arguments['p_operation_id'])
        if op in self.operations:
            old_arguments, result = self.operations[op]
            if old_arguments != arguments:
                raise CloudSyncError('operation reused with different content')
            return copy.deepcopy(result)
        qid = arguments['p_id']
        old = self.rows.get(qid)
        if old and old['user_id'] != user:
            raise CloudSyncError('forbidden')
        if (old and (old['version'] != arguments['p_base_version'] or old['deleted'] and not arguments['p_deleted'])) or (not old and arguments['p_base_version'] != 0):
            result = {'status': 'conflict', 'record': copy.deepcopy(old)}
        else:
            seq = self.sequences.get(user, 0) + 1
            self.sequences[user] = seq
            self.rows[qid] = dict(id=qid, user_id=user, version=arguments['p_base_version'] + 1,
                                 seq=seq, deleted=arguments['p_deleted'], payload=copy.deepcopy(arguments['p_payload']))
            result = {'status': 'applied', 'record': copy.deepcopy(self.rows[qid])}
        self.operations[op] = (copy.deepcopy(arguments), copy.deepcopy(result))
        return result


class Client:
    def __init__(self, backend, user):
        self.backend, self.user = backend, user
        self.fail_after_commit = False
        self.fail_upload = False
        self.corrupt_download = False
        self.sent = []

    def rpc(self, name, arguments):
        result = self.backend.rpc(self.user, name, arguments)
        if name == 'flandre_sync_push':
            self.sent.append(copy.deepcopy(arguments))
            if self.fail_after_commit:
                self.fail_after_commit = False
                raise CloudSyncError('response lost after commit')
        return result

    def upload(self, image, source):
        if self.fail_upload:
            raise CloudSyncError('upload failed')
        assert image['key'].startswith(self.user + '/')
        self.backend.images[image['key']] = Path(source).read_bytes()

    def download(self, key):
        if not key.startswith(self.user + '/'):
            raise CloudSyncError('forbidden')
        if self.corrupt_download:
            return b'corrupted image'
        return self.backend.images[key]


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.guest = self.root / 'guest'
        self.a = self.root / 'a'
        self.other = self.root / 'other-device-a'
        self.b = self.root / 'b'
        for path in (self.guest, self.a, self.other, self.b):
            store.initialize(path / 'questions.db')
        self.local = SyncStore(self.a, 'USER_A', ENVIRONMENT_ID)
        self.second = SyncStore(self.other, 'USER_A', ENVIRONMENT_ID)
        self.foreign = SyncStore(self.b, 'USER_B', ENVIRONMENT_ID)
        for value in (self.local, self.second, self.foreign):
            value.bind()
        self.backend = Backend()
        self.client = Client(self.backend, 'USER_A')
        self.original = self.root / 'sample.png'
        image = QImage(30, 20, QImage.Format.Format_RGB32)
        image.fill(0xffffff)
        assert image.save(str(self.original))

    def tearDown(self):
        self.temporary.cleanup()

    @contextmanager
    def active(self, path):
        with patch.object(store, 'DATA_DIR', path), patch.object(store, 'DATABASE_PATH', path / 'questions.db'), \
                patch.object(attachments, 'ATTACHMENTS_DIR', path / 'attachments'), \
                patch.object(backup, 'ATTACHMENTS_DIR', path / 'attachments'):
            yield

    def question(self, path=None, image=False):
        with self.active(path or self.a):
            qid = store.save_question({'stem': 'Question', 'notes': 'Keep notes', 'options': {'A':'One','B':'Two'}})
            if image:
                attachments.import_image(qid, self.original)
            return qid

    def row(self, path=None):
        with store._connection((path or self.a) / 'questions.db') as db:
            return dict(db.execute('SELECT * FROM questions LIMIT 1').fetchone())

    def test_two_devices_question_notes_mastery_and_original_image_round_trip(self):
        qid = self.question(image=True)
        with self.active(self.a):
            store.record_attempt(qid, 'correct', 3, 'mastered')
        synchronize(self.local, self.client)
        synchronize(self.second, Client(self.backend, 'USER_A'))
        self.assertEqual(self.row(self.other)['notes'], 'Keep notes')
        with store._connection(self.other / 'questions.db') as db:
            self.assertEqual(db.execute('SELECT mastery FROM review_state').fetchone()[0], 'mastered')
            image = db.execute('SELECT relative_path FROM attachments').fetchone()[0]
            self.assertEqual((self.other / image).read_bytes(), self.original.read_bytes())
            self.assertEqual(db.execute('SELECT count(*) FROM practice_attempts').fetchone()[0], 0)
        self.assertEqual(self.local.status()['pending'], 0)
        with self.active(self.other):
            store.save_question_notes(self.row(self.other)['id'], 'Edited on another device')
        synchronize(self.second, Client(self.backend, 'USER_A'))
        synchronize(self.local, self.client)
        self.assertEqual(self.row()['notes'], 'Edited on another device')

    def test_guest_not_automatically_queued_and_accounts_cannot_mix(self):
        self.question(self.guest)
        with store._connection(self.guest / 'questions.db') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sync_entities').fetchone()[0], 0)
        self.question()
        synchronize(self.local, self.client)
        synchronize(self.foreign, Client(self.backend, 'USER_B'))
        with self.foreign.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM questions').fetchone()[0], 0)
        with self.assertRaisesRegex(ValueError, '其他账号'):
            SyncStore(self.a, 'USER_B', ENVIRONMENT_ID).bind()
        self.assertNotEqual(account_directory(self.guest, 'USER_A'), account_directory(self.guest, 'USER_B'))

    def test_remote_change_preserves_old_edit_draft_without_restoring_stale_fields(self):
        self.question()
        synchronize(self.local, self.client)
        synchronize(self.second, Client(self.backend, 'USER_A'))
        with self.active(self.other):
            qid = self.row(self.other)['id']
            store.save_workspace(f'question:{qid}', {'question': {'stem': 'Unsaved draft'}})
        with self.active(self.a):
            store.save_question_notes(self.row()['id'], 'New cloud notes')
        synchronize(self.local, self.client)
        result = synchronize(self.second, Client(self.backend, 'USER_A'))
        self.assertEqual(result['archived_drafts'], 1)
        with self.active(self.other):
            self.assertIsNone(store.load_workspace(f'question:{qid}'))
        files = list((self.other / 'attachments/_conflicts').rglob('local-edit-draft.json'))
        self.assertEqual(json.loads(files[0].read_text(encoding='utf-8'))['draft']['question']['stem'], 'Unsaved draft')
        self.assertEqual(self.row(self.other)['notes'], 'New cloud notes')

    def test_changes_and_queue_roll_back_in_one_transaction(self):
        with self.local.connection() as db:
            with self.assertRaises(RuntimeError):
                try:
                    db.execute("INSERT INTO questions(stem) VALUES('Will roll back')")
                    raise RuntimeError('business error')
                except RuntimeError:
                    db.rollback()
                    raise
        self.assertEqual(self.local.status()['pending'], 0)

    def test_lost_response_retries_identical_operation_after_restart(self):
        qid = self.question(image=True)
        self.client.fail_after_commit = True
        with self.assertRaises(CloudSyncError):
            synchronize(self.local, self.client)
        with self.active(self.a):
            store.save_question_notes(qid, 'Changed while retry pending')
        restarted = SyncStore(self.a, 'USER_A', ENVIRONMENT_ID)
        synchronize(restarted, self.client)
        self.assertEqual(self.client.sent[0], self.client.sent[1])
        self.assertEqual(len(self.backend.rows), 1)
        self.assertEqual(next(iter(self.backend.rows.values()))['version'], 2)
        self.assertEqual(restarted.status()['pending'], 0)

    def test_deleting_original_after_prepared_snapshot_does_not_break_retry(self):
        qid = self.question(image=True)
        self.client.fail_after_commit = True
        with self.assertRaises(CloudSyncError):
            synchronize(self.local, self.client)
        with self.active(self.a):
            attachments.delete_question_images(qid)
        synchronize(self.local, self.client)
        self.assertTrue(next(iter(self.backend.rows.values()))['deleted'])
        self.assertEqual(self.local.status()['pending'], 0)

    def test_upload_failure_never_publishes_broken_attachment_link(self):
        self.question(image=True)
        self.client.fail_upload = True
        with self.assertRaises(CloudSyncError):
            synchronize(self.local, self.client)
        self.assertFalse(self.backend.rows)
        self.assertEqual(self.local.status()['pending'], 1)

    def test_conflict_preserves_notes_and_both_versions(self):
        qid = self.question()
        synchronize(self.local, self.client)
        synchronize(self.second, Client(self.backend, 'USER_A'))
        with self.active(self.a):
            store.save_question_notes(qid, 'Local note')
        with self.active(self.other):
            store.save_question_notes(self.row(self.other)['id'], 'Remote note')
        synchronize(self.second, Client(self.backend, 'USER_A'))
        synchronize(self.local, self.client)
        self.assertEqual(self.row()['notes'], 'Local note')
        conflict = self.local.conflicts()[0]
        self.assertEqual(json.loads(conflict['conflict'])['payload']['question']['notes'], 'Remote note')
        self.local.resolve(conflict['id'], False, self.client)
        self.assertEqual(self.row()['notes'], 'Remote note')
        self.assertFalse(self.local.conflicts())
        snapshots = list((self.a / 'attachments' / '_conflicts').rglob('local-question.json'))
        self.assertEqual(json.loads(snapshots[0].read_text(encoding='utf-8'))['question']['notes'], 'Local note')

    def test_keep_local_conflict_becomes_new_version_without_silent_overwrite(self):
        qid = self.question()
        synchronize(self.local, self.client)
        synchronize(self.second, Client(self.backend, 'USER_A'))
        with self.active(self.a):
            store.save_question_notes(qid, 'Local choice')
        with self.active(self.other):
            store.save_question_notes(self.row(self.other)['id'], 'Other choice')
        synchronize(self.second, Client(self.backend, 'USER_A'))
        synchronize(self.local, self.client)
        self.local.resolve(self.local.conflicts()[0]['id'], True, self.client)
        synchronize(self.local, self.client)
        self.assertEqual(next(iter(self.backend.rows.values()))['payload']['question']['notes'], 'Local choice')
        self.assertEqual(next(iter(self.backend.rows.values()))['version'], 3)

    def test_remote_deletion_conflicts_with_offline_edit_and_explicit_recovery_has_new_id(self):
        qid = self.question(image=True)
        synchronize(self.local, self.client)
        original_id = next(iter(self.backend.rows))
        synchronize(self.second, Client(self.backend, 'USER_A'))
        with self.active(self.a):
            store.save_question_notes(qid, 'Offline edit')
        with self.active(self.other):
            attachments.delete_question_images(self.row(self.other)['id'])
        synchronize(self.second, Client(self.backend, 'USER_A'))
        synchronize(self.local, self.client)
        self.assertEqual(self.row()['notes'], 'Offline edit')
        self.local.resolve(self.local.conflicts()[0]['id'], True, self.client)
        synchronize(self.local, self.client)
        self.assertTrue(self.backend.rows[original_id]['deleted'])
        self.assertEqual(len(self.backend.rows), 2)
        self.assertEqual(sum(not row['deleted'] for row in self.backend.rows.values()), 1)

    def test_delete_tombstone_and_integer_id_reuse_do_not_resurrect_old_question(self):
        qid = self.question()
        synchronize(self.local, self.client)
        old_id = next(iter(self.backend.rows))
        synchronize(self.second, Client(self.backend, 'USER_A'))
        with self.active(self.a):
            store.delete_question(qid)
            new_id = store.save_question({'stem':'Brand new'})
        self.assertEqual(qid, new_id)
        synchronize(self.local, self.client)
        synchronize(self.second, Client(self.backend, 'USER_A'))
        self.assertTrue(self.backend.rows[old_id]['deleted'])
        self.assertEqual(self.row(self.other)['stem'], 'Brand new')

    def test_bad_cursor_does_not_apply_page_or_advance(self):
        self.question()
        synchronize(self.local, self.client)
        client = Client(self.backend, 'USER_A')
        original = client.rpc
        def malformed(name, arguments):
            result = original(name, arguments)
            result['cursor'] += 1
            return result
        client.rpc = malformed
        with self.assertRaisesRegex(CloudSyncError, '游标'):
            synchronize(self.second, client)
        self.assertEqual(self.second.status()['cursor'], 0)
        with self.second.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM questions').fetchone()[0], 0)

    def test_corrupted_image_keeps_page_cursor_and_question_unapplied(self):
        self.question(image=True)
        synchronize(self.local, self.client)
        client = Client(self.backend, 'USER_A')
        client.corrupt_download = True
        with self.assertRaisesRegex(ValueError, '校验'):
            synchronize(self.second, client)
        self.assertEqual(self.second.status()['cursor'], 0)
        with self.second.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM questions').fetchone()[0], 0)

    def test_foreign_or_traversal_records_are_rejected(self):
        self.question(image=True)
        synchronize(self.local, self.client)
        record = copy.deepcopy(next(iter(self.backend.rows.values())))
        record['user_id'] = 'USER_B'
        with self.assertRaisesRegex(ValueError, '不属于'):
            self.second.validate_record(record)
        record['user_id'] = 'USER_A'
        record['payload']['attachments'][0]['key'] = 'USER_A/../private.png'
        with self.assertRaisesRegex(ValueError, '路径'):
            self.second.validate_record(record)

    def test_import_is_explicit_backed_up_and_repeated_source_does_not_duplicate(self):
        self.question(self.guest, image=True)
        source_before = (self.guest / 'questions.db').read_bytes()
        result = self.local.import_guest(self.guest)
        self.assertEqual(result['imported'], 1)
        self.assertTrue(Path(result['backup']).is_file())
        self.assertEqual((self.guest / 'questions.db').read_bytes(), source_before)
        self.assertEqual(self.local.import_guest(self.guest)['imported'], 0)
        self.assertEqual(self.local.status()['pending'], 1)
        self.assertEqual(self.row()['notes'], 'Keep notes')

    def test_import_missing_image_rolls_back_questions_and_queue(self):
        qid = self.question(self.guest, image=True)
        with self.active(self.guest):
            path = attachments.attachment_file(store.list_attachments(qid)[0]['relative_path'])
            path.unlink()
        with self.assertRaises((KeyError, ValueError)):
            self.local.import_guest(self.guest)
        self.assertEqual(self.local.status()['pending'], 0)
        with self.local.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM questions').fetchone()[0], 0)

    def test_account_backup_contains_frozen_operations_and_staged_images(self):
        self.question(image=True)
        pending = self.local.prepare()
        destination = self.root / 'backup.zip'
        with self.active(self.a):
            backup.create_backup(destination)
        import zipfile
        with zipfile.ZipFile(destination) as archive:
            self.assertTrue(any(name.startswith('attachments/_sync_staging/' + pending['operation_id']) for name in archive.namelist()))
            archived_db = self.root / 'archived.db'
            archived_db.write_bytes(archive.read('database.sqlite3'))
        with closing(sqlite3.connect(archived_db)) as db:
            self.assertEqual(db.execute('SELECT operation_id FROM sync_outbox').fetchone()[0], pending['operation_id'])

    def test_migration_preserves_question_id_and_creates_pre_upgrade_copy(self):
        path = self.root / 'old.db'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE questions(id INTEGER PRIMARY KEY,stem TEXT NOT NULL,subject TEXT NOT NULL DEFAULT '',question_type TEXT NOT NULL DEFAULT '',answer TEXT NOT NULL DEFAULT '',explanation TEXT NOT NULL DEFAULT '',is_wrong INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            db.execute("INSERT INTO questions VALUES(42,'Old question','','','','',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
            db.execute('PRAGMA user_version=1')
        store.initialize(path)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT id,stem FROM questions').fetchone(), (42,'Old question'))
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], store.SCHEMA_VERSION)
        self.assertEqual(len(list(self.root.glob('pre-schema-v1-*.db'))), 1)

    def test_expired_session_stops_network_and_closed_session_has_no_token(self):
        session = CloudSession({'user_id':'USER_A','access_token':'SECRET_TOKEN','expires_in':7200}, 'test_a')
        session.expires_at = 0
        with patch('app.services.cloud_sync.urllib.request.build_opener') as network:
            with self.assertRaisesRegex(CloudSyncError, '到期'):
                CloudClient(session).rpc('flandre_sync_pull', {'p_after':0,'p_limit':10})
            network.assert_not_called()
        session.close()
        self.assertEqual(session.token, '')

    def test_http_user_token_uses_fixed_host_without_redirects_and_never_returns_server_error(self):
        session = CloudSession({'user_id':'USER_A','access_token':'SECRET_TOKEN','expires_in':7200}, 'test_a')
        response = BytesIO(b'{"records":[],"cursor":0}')
        response.status = 200
        with patch('app.services.cloud_sync.urllib.request.build_opener') as build:
            build.return_value.open.return_value = response
            result = CloudClient(session).rpc('flandre_sync_pull', {'p_after':0,'p_limit':10})
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, f'https://{ENVIRONMENT_ID}.api.tcloudbasegateway.com/v1/rdb/rest/rpc/flandre_sync_pull')
            self.assertEqual(request.get_header('Authorization'), 'Bearer SECRET_TOKEN')
            self.assertNotIn('SECRET', str(result))
            build.return_value.open.assert_called_once()


if __name__ == '__main__':
    unittest.main()
