"""Standalone-only human approval receipts; no private key or provider calls."""
import re
import os
import sqlite3
import stat
from contextlib import closing
import threading
import time
from scripts.task_proposals import canonical, node_verify, key_path_checked, DEFAULT_PUBKEY

DOMAIN = b'DSH_NATIVE_SDK_APPROVAL_V1\n'
FIELDS = {'action','taskId','subject','generation','approvalId','outcome','nonce','exp','sig'}
SUBJECT = re.compile(r'standalone:u-[a-f0-9]{32}:dsh-python-sdk:(off|on):[a-f0-9]{24}')


class NativeApprovalReceipts:
    def __init__(self, *, journal_file, key_file=None, clock=time.time,
                 verifier=node_verify, owner_uid=0, check_owner=True):
        self.key_file,self.clock,self.verifier=key_file or os.environ.get('DSH_CONFIRM_PUBKEY_FILE',DEFAULT_PUBKEY),clock,verifier
        self.owner_uid,self.check_owner=owner_uid,check_owner
        self.lock=threading.Lock()
        self.journal_file=journal_file
        # Parent must already exist in the protected controller's durable
        # storage. Never create/chown a user's home or state directory here.
        parent=os.path.abspath(os.path.dirname(journal_file))
        current=parent
        while True:
            info=os.lstat(current)
            if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or (check_owner and (info.st_uid!=owner_uid or info.st_mode&0o022))):
                raise ValueError('PROTECTED_APPROVAL_JOURNAL_REQUIRED')
            next_parent=os.path.dirname(current)
            if current==next_parent:break
            current=next_parent
        fd=os.open(journal_file,os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1
                    or (check_owner and (info.st_uid!=owner_uid or stat.S_IMODE(info.st_mode)!=0o600))):
                raise ValueError('PROTECTED_APPROVAL_JOURNAL_REQUIRED')
        finally:os.close(fd)
        with closing(sqlite3.connect(self.journal_file)) as db, db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS consumed (nonce TEXT PRIMARY KEY, expires INTEGER NOT NULL)')

    def consume(self, receipt, *, task_id, subject, generation, approval_id, outcome):
        if not isinstance(receipt,dict) or set(receipt)!=FIELDS:
            raise ValueError('SDK_SIGNED_APPROVAL_BINDING_REQUIRED')
        expected={'action':'native-sdk-approval','taskId':task_id,'subject':subject,
                  'generation':generation,'approvalId':approval_id,'outcome':outcome}
        if any(receipt[k]!=v for k,v in expected.items()):
            raise ValueError('FOREIGN_NATIVE_APPROVAL_RECEIPT')
        if (not isinstance(subject,str) or SUBJECT.fullmatch(subject) is None
                or not isinstance(task_id,str) or re.fullmatch(r'[a-f0-9]{32}',task_id) is None
                or not isinstance(generation,str) or re.fullmatch(r'[A-Za-z0-9_.@:-]{1,128}',generation) is None
                or not isinstance(approval_id,str) or not 1<=len(approval_id)<=256
                or not isinstance(outcome,str) or outcome not in {'allowed-once','rejected','cancelled'}):
            raise ValueError('INVALID_NATIVE_APPROVAL_BINDING')
        exp=receipt['exp'];nonce=receipt['nonce'];now=int(self.clock())
        if (type(exp) is not int or not now<=exp<=now+120
                or not isinstance(nonce,str) or re.fullmatch(r'[A-Za-z0-9_-]{16,64}',nonce) is None
                or not isinstance(receipt['sig'],str) or len(receipt['sig'])>128):
            raise ValueError('INVALID_NATIVE_APPROVAL_RECEIPT')
        key=key_path_checked(self.key_file,self.owner_uid,self.check_owner)
        signed={k:v for k,v in receipt.items() if k!='sig'}
        if not self.verifier(key,DOMAIN+canonical(signed),receipt['sig']):
            raise ValueError('INVALID_NATIVE_APPROVAL_SIGNATURE')
        # Consume before invoking a bridge. An uncertain bridge result cannot
        # authorize a second attempt with the same human decision.
        with self.lock:
            now=int(self.clock())
            if now>exp:raise ValueError('EXPIRED_NATIVE_APPROVAL_RECEIPT')
            with closing(sqlite3.connect(self.journal_file)) as db, db:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('BEGIN IMMEDIATE')
                db.execute('DELETE FROM consumed WHERE expires < ?',(now,))
                if db.execute('SELECT 1 FROM consumed WHERE nonce=?',(nonce,)).fetchone():
                    raise ValueError('REPLAYED_NATIVE_APPROVAL_RECEIPT')
                if db.execute('SELECT count(*) FROM consumed').fetchone()[0]>=4096:
                    raise ValueError('NATIVE_APPROVAL_RECEIPT_CAPACITY')
                db.execute('INSERT INTO consumed VALUES (?,?)',(nonce,exp))
        return True
