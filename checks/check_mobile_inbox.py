"""Synthetic account-isolation, receipt recovery and picture-integrity checks."""
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from app.database import store
from app.services import attachments, recognition_drafts, backup
from app.services.cloud_sync import CloudSession, CloudSyncError, ENVIRONMENT_ID
from app.services.cloud_sync_store import SyncStore, dump
from app.services.mobile_inbox import InboxClient, InboxStore


class FakeClient:
    def __init__(self, row, images):
        self.row, self.images = copy.deepcopy(row), images
        self.fail_ack = False
        self.corrupt = False

    def download(self,key):
        return b'bad picture' if self.corrupt else self.images[key]

    def rpc(self,name,args):
        if name=='flandre_inbox_pull':
            rows=[copy.deepcopy(self.row)] if self.row['seq']>args['p_after'] else []
            return {'records':rows,'cursor':self.row['seq'] if rows else args['p_after']}
        if name=='flandre_inbox_finish':
            assert args['p_id']==self.row['id'].replace('-','')
            if self.row['status']=='pending':
                self.row['status']='processed';self.row['seq']+=1
            if self.fail_ack:
                self.fail_ack=False
                raise CloudSyncError('Lost acknowledgement after cloud commit')
            return {'record':copy.deepcopy(self.row)}
        raise AssertionError(name)


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        for name,user in [('a','USER_A'),('b','USER_B')]:
            path=self.root/name;store.initialize(path/'questions.db');SyncStore(path,user,ENVIRONMENT_ID).bind()
        self.local=InboxStore(self.root/'a','USER_A')
        iid=uuid4().hex;images=[];contents={}
        for role,color in [('original',0xffffff),('crop',0xffcccc)]:
            path=self.root/(role+'.png');image=QImage(20,10,QImage.Format.Format_RGB32);image.fill(color);assert image.save(str(path))
            data=path.read_bytes();aid=uuid4().hex;digest=hashlib.sha256(data).hexdigest()
            key=f'USER_A/{iid}/{aid}/{digest}.png'
            images.append(dict(id=aid,key=key,sha256=digest,size=len(data),mime_type='image/png',role=role));contents[key]=data
        self.row=dict(id=iid,user_id='USER_A',seq=1,status='pending',payload=dict(source_name='Paper question',note='Math paper #4',images=images))
        self.client=FakeClient(self.row,contents)

    def tearDown(self):
        self.temp.cleanup()

    @contextmanager
    def active(self):
        with patch.object(store,'DATA_DIR',self.local.root),patch.object(store,'DATABASE_PATH',self.local.database),\
            patch.object(attachments,'ATTACHMENTS_DIR',self.local.root/'attachments'),patch.object(backup,'ATTACHMENTS_DIR',self.local.root/'attachments'):
            yield

    def test_receive_draft_resume_no_question_until_confirm_and_both_originals(self):
        self.assertEqual(self.local.receive(self.client),1)
        self.assertEqual(self.local.receive(self.client),0)
        with self.active():
            key=self.local.draft(self.row['id']);self.assertEqual(self.local.draft(self.row['id']),key)
            state,path=recognition_drafts.load(key)
            self.assertEqual(state['source_name'],'Paper question')
            with self.local.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM questions').fetchone()[0],0)
            original=self.local.original_for_draft(key)
            ids=attachments.import_recognized_questions([dict(stem='Limit',answer='42')],path,key,[original])
            self.assertEqual(len(store.list_attachments(ids[0])),2)
            with self.local.connection() as db:
                self.assertEqual(db.execute('SELECT local_done,needs_ack FROM mobile_inbox').fetchone()[:],(1,1))
                self.assertEqual(db.execute('SELECT dirty FROM sync_entities').fetchone()[0],1)
            with self.assertRaises(ValueError):self.local.draft(self.row['id'])
            with self.assertRaises(ValueError):attachments.import_recognized_questions([dict(stem='Duplicate')],path,key)
            self.client.fail_ack=True
            with self.assertRaises(CloudSyncError):self.local.receive(self.client)
            self.assertEqual(len(self.local.pending()),0)
            self.local.receive(self.client)
            with self.local.connection() as db:
                self.assertEqual(db.execute('SELECT status,needs_ack FROM mobile_inbox').fetchone()[:],('processed',0))
                self.assertEqual(db.execute('SELECT count(*) FROM questions').fetchone()[0],1)

    def test_failed_batch_rolls_back_receipt_and_question(self):
        self.local.receive(self.client)
        with self.active():
            key=self.local.draft(self.row['id']);state,path=recognition_drafts.load(key)
            with patch.object(store,'save_recognized_questions',side_effect=RuntimeError('Disk failure')):
                with self.assertRaises(RuntimeError):attachments.import_recognized_questions([dict(stem='No partial import')],path,key)
            self.assertEqual(len(self.local.pending()),1)
            recognition_drafts.load(key)
            with self.local.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM questions').fetchone()[0],0)

    def test_bad_image_and_cursor_do_not_advance(self):
        self.client.corrupt=True
        with self.assertRaises(CloudSyncError):self.local.receive(self.client)
        with self.local.connection() as db:self.assertIsNone(db.execute("SELECT value FROM sync_state WHERE key='inbox_cursor'").fetchone())
        self.client.corrupt=False
        real=self.client.rpc
        def bad(name,args):
            result=real(name,args);result['cursor']=50;return result
        with patch.object(self.client,'rpc',bad):
            with self.assertRaises(CloudSyncError):self.local.receive(self.client)
        self.assertEqual(len(self.local.pending()),0)

    def test_cross_account_and_spoofed_paths_rejected(self):
        foreign=InboxStore(self.root/'b','USER_B')
        with self.assertRaises(CloudSyncError):foreign.receive(self.client)
        for field,value in [('key','USER_B/secret.png'),('size',True),('role','other')]:
            row=copy.deepcopy(self.row);row['payload']['images'][0][field]=value
            with self.assertRaises(CloudSyncError):self.local.validate(row)

    def test_original_mutation_stops_cursor_and_preserves_draft(self):
        self.local.receive(self.client)
        with self.active():key=self.local.draft(self.row['id'])
        row=copy.deepcopy(self.row);row['seq']=2;row['payload']['note']='changed immutable payload';self.client.row=row
        with self.assertRaises(CloudSyncError):self.local.receive(self.client)
        with self.local.connection() as db:
            self.assertEqual(db.execute("SELECT value FROM sync_state WHERE key='inbox_cursor'").fetchone()[0],'1')
        with self.active():recognition_drafts.load(key)

    def test_backup_contains_inbox_originals_and_checkpoint(self):
        self.local.receive(self.client)
        with self.active():
            self.local.draft(self.row['id'])
            path=self.root/'backup.zip';backup.create_backup(path,data_dir=self.local.root)
            import zipfile
            with zipfile.ZipFile(path) as archive:
                names=archive.namelist()
                self.assertEqual(len([n for n in names if '/inbox/' in n]),2)
                self.assertEqual(len([n for n in names if '/drafts/' in n]),1)

    def test_processed_elsewhere_stops_local_stale_draft(self):
        self.local.receive(self.client)
        with self.active():
            key=self.local.draft(self.row['id']);state,path=recognition_drafts.load(key)
            self.client.row.update(status='processed',seq=2);self.local.receive(self.client)
            with self.assertRaises(ValueError):attachments.import_recognized_questions([dict(stem='Stale')],path,key)
            recognition_drafts.load(key)

    def test_storage_route_private_and_expired_session(self):
        session=CloudSession(dict(user_id='USER_A',access_token='memory-only',expires_in=7200),'A')
        client=InboxClient(session);key=self.row['payload']['images'][0]['key']
        self.assertTrue(client._key(key).startswith('/v1/storages/object/flandre-inbox-images/USER_A/'))
        with self.assertRaises(CloudSyncError):client._key('USER_B/'+key.split('/',1)[1])
        session.close()
        with self.assertRaises(CloudSyncError):client.download(key)

    def test_re_recognition_branches_cannot_import_the_same_receipt_twice(self):
        from app.services.mobile_inbox import link_replacement_draft
        self.local.receive(self.client)
        with self.active():
            key=self.local.draft(self.row['id']);state,path=recognition_drafts.load(key)
            replacement,new_state,new_path=recognition_drafts.create(path,'')
            link_replacement_draft(key,replacement)
            attachments.import_recognized_questions([dict(stem='Reviewed replacement')],new_path,replacement,
                                                   [self.local.original_for_draft(replacement)])
            with self.assertRaises(ValueError):attachments.import_recognized_questions([dict(stem='Old fork')],path,key)
            with self.local.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM questions').fetchone()[0],1)

    def test_inbox_window_opens_persistent_draft_and_blocks_busy_close(self):
        from app.ui.mobile_inbox_dialog import MobileInboxDialog
        from PySide6.QtWidgets import QWidget
        self.local.receive(self.client)
        class Window(QWidget):
            def __init__(window):
                super().__init__();window.cloud_directory=self.local.root
                window.cloud_session=type('Session',(),dict(user_id='USER_A'))()
                window.opened=None
            def start_image_recognition(window,**args):window.opened=args['resume_key']
        with self.active():
            window=Window();dialog=MobileInboxDialog(window);dialog.show();app.processEvents()
            self.assertEqual(dialog.list.count(),1)
            dialog.worker=object();self.assertFalse(dialog.close());dialog.worker=None
            dialog.open_image();self.assertTrue(window.opened.startswith('recognition:'))
            self.assertFalse(dialog.isVisible());recognition_drafts.load(window.opened)
            window.close()


if __name__=='__main__':
    app=QApplication.instance() or QApplication([])
    unittest.main()
