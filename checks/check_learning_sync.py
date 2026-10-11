"""Isolated learning protocol checks; no personal data or live cloud requests."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_cloud_sync as protocol_checks
from check_cloud_sync import Client
from app.database import store, vocabulary
from app.services.cloud_sync import synchronize, CloudSyncError
from app.services.learning_sync import LearningStore, validate_payload


class LearningTests(protocol_checks.SyncTests):
    def word(self, root=None, name='hello', meaning='你好'):
        with self.active(root or self.a):
            return vocabulary.save_word(dict(word=name, meaning=meaning, book='英语'))

    def words(self, root=None):
        with self.active(root or self.a):
            return [dict(row) for row in vocabulary.list_words()]

    def test_words_progress_and_attempts_round_trip_without_duplicate_statistics(self):
        word = self.word()
        question = self.question()
        with self.active(self.a):
            vocabulary.record_review(word, 'known')
            store.record_attempt(question, 'incorrect', 8, 'unsure', mistake_reason='计算错误', user_answer='2')
        synchronize(self.local, self.client)
        synchronize(self.second, Client(self.backend, 'USER_A'))
        self.assertEqual(self.words()[0]['review_count'], self.words(self.other)[0]['review_count'])
        self.assertEqual(self.words(self.other)[0]['book'], '英语')
        self.assertEqual(self.words(self.other)[0]['mastery'], 'mastered')
        for _ in range(2):
            synchronize(self.local, self.client)
            synchronize(self.second, Client(self.backend, 'USER_A'))
        with self.active(self.other):
            self.assertEqual(store.learning_statistics()['total']['attempts'], 1)
            self.assertEqual(store.list_attempts()[0]['user_answer'], '2')
            self.assertEqual(store.list_attempts()[0]['mistake_reason'], '计算错误')

    def test_lost_learning_confirmation_reuses_operation_after_restart(self):
        self.word()
        class LostClient(Client):
            lost = False
            def rpc(client, name, arguments):
                result = super().rpc(name, arguments)
                if name == 'flandre_learning_push' and not client.lost:
                    client.lost = True
                    raise CloudSyncError('synthetic response lost')
                return result
        client = LostClient(self.backend, 'USER_A')
        with self.assertRaises(CloudSyncError):
            synchronize(self.local, client)
        pending = LearningStore(self.local).prepare()
        from app.services.cloud_sync_store import SyncStore
        restarted = SyncStore(self.a, 'USER_A', self.local.environment_id)
        self.assertEqual(LearningStore(restarted).prepare(), pending)
        synchronize(restarted, client)
        self.assertEqual(len(self.backend.learning_rows), 1)
        self.assertEqual(restarted.status()['pending'], 0)

    def test_concurrent_word_edit_preserves_local_until_explicit_choice(self):
        word = self.word()
        synchronize(self.local, self.client)
        synchronize(self.second, Client(self.backend, 'USER_A'))
        other = self.words(self.other)[0]
        with self.active(self.a):
            vocabulary.save_word(dict(word='hello', meaning='本机修改'), word)
        with self.active(self.other):
            vocabulary.save_word(dict(word='hello', meaning='另一设备修改'), other['id'])
        synchronize(self.second, Client(self.backend, 'USER_A'))
        synchronize(self.local, self.client)
        self.assertEqual(self.words()[0]['meaning'], '本机修改')
        self.assertEqual(self.local.status()['conflicts'], 1)
        entity = LearningStore(self.local).conflicts()[0]['id']
        self.local.resolve(entity, False, self.client)
        synchronize(self.local, self.client)
        self.assertEqual(self.words()[0]['meaning'], '另一设备修改')
        self.assertTrue(list((self.a/'attachments/_conflicts').glob('learning-*.json')))

    def test_same_word_created_on_both_devices_can_choose_one_identity(self):
        self.word(meaning='本机词条')
        self.word(self.other, meaning='手机词条')
        synchronize(self.second, Client(self.backend, 'USER_A'))
        synchronize(self.local, self.client)
        conflict = LearningStore(self.local).conflicts()[0]
        self.local.resolve(conflict['id'], True, self.client)
        synchronize(self.local, self.client)
        synchronize(self.second, Client(self.backend, 'USER_A'))
        for conflict in LearningStore(self.second).conflicts():
            self.second.resolve(conflict['id'], False, self.client)
        synchronize(self.second, Client(self.backend, 'USER_A'))
        self.assertEqual(len(self.words()), 1)
        self.assertEqual(len(self.words(self.other)), 1)
        self.assertEqual(self.words(self.other)[0]['meaning'], '本机词条')

    def test_word_deletion_and_question_deletion_preserve_history_snapshot(self):
        word = self.word()
        question = self.question()
        with self.active(self.a):
            store.record_attempt(question, 'correct', 3, 'mastered', user_answer='A')
        synchronize(self.local, self.client)
        synchronize(self.second, Client(self.backend, 'USER_A'))
        with self.active(self.a):
            vocabulary.delete_word(word)
            store.delete_question(question)
        synchronize(self.local, self.client)
        synchronize(self.second, Client(self.backend, 'USER_A'))
        self.assertEqual(self.words(self.other), [])
        with self.active(self.other):
            self.assertEqual(store.learning_statistics()['total']['attempts'], 1)
            self.assertEqual(store.list_attempts()[0]['stem'], 'Question')

    def test_malformed_learning_page_does_not_advance_cursor_or_partial_apply(self):
        self.word()
        synchronize(self.local, self.client)
        class BadClient(Client):
            def rpc(client, name, args):
                page = super().rpc(name, args)
                if name == 'flandre_learning_pull' and page['records']:
                    bad = copy.deepcopy(page['records'][0]);bad['seq'] += 1;bad['payload']['review_count'] = True
                    page['records'].append(bad);page['cursor'] = bad['seq']
                return page
        with self.assertRaises(ValueError):
            synchronize(self.second, BadClient(self.backend, 'USER_A'))
        self.assertEqual(self.words(self.other), [])
        self.assertEqual(LearningStore(self.second).status()['cursor'], 0)
        with self.assertRaises(ValueError):
            LearningStore(self.foreign).record(next(iter(self.backend.learning_rows.values())))

    def test_close_upload_only_keeps_remote_word_and_question_out_of_active_editors(self):
        self.word(self.other)
        self.question(self.other)
        synchronize(self.second, Client(self.backend, 'USER_A'))
        synchronize(self.local, self.client, pull=False)
        self.assertEqual(self.words(), [])
        with self.local.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM questions').fetchone()[0], 0)
        synchronize(self.local, self.client)
        self.assertEqual(len(self.words()), 1)

    def test_new_local_edit_after_frozen_word_is_still_pending(self):
        word = self.word()
        frozen = LearningStore(self.local).prepare()
        with self.active(self.a):
            vocabulary.save_word(dict(word='hello', meaning='后来编辑'), word)
        remote = self.backend.rpc('USER_A','flandre_learning_push',dict(p_id=frozen['entity_id'],p_operation_id=frozen['operation_id'],p_base_version=0,p_deleted=False,p_kind='word',p_payload=json.loads(frozen['payload'])))['record']
        LearningStore(self.local).acknowledge(frozen, remote)
        self.assertEqual(self.local.status()['pending'], 1)
        synchronize(self.local, self.client)
        self.assertEqual(next(iter(self.backend.learning_rows.values()))['payload']['meaning'], '后来编辑')

    def test_shared_desktop_android_fields_preserve_utc_and_history_snapshot(self):
        records = json.loads((Path(__file__).parent/'fixtures/learning_exchange.json').read_text(encoding='utf-8'))
        learning = LearningStore(self.local)
        records = [learning.record(row) for row in records]
        learning.apply(records, 2)
        with self.local.connection() as db:
            for record in records:
                entity = db.execute('SELECT * FROM learning_entities WHERE id=?',(record['id'],)).fetchone()
                self.assertEqual(learning.content(db, entity), record['payload'])
        question = self.question()
        with self.active(self.a):
            store.record_attempt(question, 'correct', 1, 'mastered')
            store.save_question({'stem':'改后的题干'}, question)
        synchronize(self.local, self.client)
        synchronize(self.second, Client(self.backend, 'USER_A'))
        with self.active(self.other):
            with store._connection() as db:
                self.assertEqual(db.execute("SELECT question_stem FROM practice_attempts WHERE question_id IS NOT NULL").fetchone()[0], 'Question')

    def test_import_guest_learning_is_explicit_and_idempotent(self):
        question = self.question(self.other)
        self.word(self.other)
        with self.active(self.other):
            store.record_attempt(question, 'correct', 3, 'mastered', user_answer='A')
        first = self.local.import_guest(self.other)
        second = self.local.import_guest(self.other)
        self.assertEqual((first['words'], first['history']), (1,1))
        self.assertEqual((second['words'], second['history']), (0,0))
        with self.active(self.a):
            self.assertEqual(store.list_attempts()[0]['user_answer'], 'A')
        with self.active(self.other):
            self.assertEqual(len(store.list_attempts()), 1)


if __name__ == '__main__':
    unittest.main()
