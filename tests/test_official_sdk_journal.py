"""Local journal I/O tests; no SDK runtime, provider or external request."""
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

import test_official_sdk_approval as approval_fixtures


class JournalTests(unittest.TestCase):
    setUp = approval_fixtures.NativeApprovalTests.setUp
    saved = approval_fixtures.NativeApprovalTests.saved
    receive = approval_fixtures.NativeApprovalTests.receive
    decide = approval_fixtures.NativeApprovalTests.decide

    def denial(self, number=5):
        error=PermissionError("synthetic journal replacement denied")
        error.winerror=number
        return error

    def test_windows_transient_replacement_persists_before_one_response(self):
        ticket=self.receive(); original=self.broker.os.replace; calls=[]
        def replace(temp,path):
            calls.append((temp,path))
            if len(calls)==1: raise self.denial()
            return original(temp,path)
        with patch.object(self.broker.sys,"platform","win32"), \
             patch.object(self.broker.os,"replace",side_effect=replace), \
             patch.object(self.broker.time,"sleep") as pause:
            self.decide(ticket)
        self.assertEqual(calls[0],calls[1])
        pause.assert_called_once_with(.01)
        self.client.respond.assert_called_once_with(1,{"outcome":"rejected"})
        self.assertEqual(self.saved()["nativeSdk"]["phase"],"running")

    def test_exhausted_denial_never_responds_and_preserves_prior_journal(self):
        ticket=self.receive(); before=(self.task.directory/"task.json").read_bytes()
        with patch.object(self.broker.sys,"platform","win32"), \
             patch.object(self.broker.os,"replace",side_effect=self.denial()) as replace, \
             patch.object(self.broker.time,"sleep") as pause, \
             self.assertRaises(PermissionError):
            self.decide(ticket)
        self.assertEqual(replace.call_count,5); self.assertEqual(pause.call_count,4)
        self.assertEqual((self.task.directory/"task.json").read_bytes(),before)
        self.client.respond.assert_not_called()
        self.assertEqual(list(self.task.directory.glob("task.json.tmp-*")),[])
        with self.assertRaises(ValueError): self.decide(ticket)
        self.client.respond.assert_not_called()

    def test_posix_permission_error_is_not_retried(self):
        with patch.object(self.broker.sys,"platform","linux"), \
             patch.object(self.broker.os,"replace",side_effect=self.denial()) as replace, \
             patch.object(self.broker.time,"sleep") as pause, \
             self.assertRaises(PermissionError):
            self.task.save()
        replace.assert_called_once(); pause.assert_not_called()

    def test_other_io_error_is_not_retried(self):
        with patch.object(self.broker.os,"replace",side_effect=OSError("synthetic disk failure")) as replace, \
             patch.object(self.broker.time,"sleep") as pause, \
             self.assertRaises(OSError):
            self.task.save()
        replace.assert_called_once(); pause.assert_not_called()

    @unittest.skipUnless(sys.platform=="win32","Windows reader-share control")
    def test_actual_windows_read_handle_release_allows_atomic_save(self):
        path=self.task.directory/"task.json"; held=path.open("r")
        self.addCleanup(held.close)
        original=self.broker.os.replace; first=threading.Event(); release=threading.Event(); seen=[]
        def replace(temp,target):
            try:return original(temp,target)
            except PermissionError as error:
                seen.append(getattr(error,"winerror",None));first.set()
                raise
        def close_reader():
            if first.wait(1):held.close();release.set()
        reader=threading.Thread(target=close_reader);reader.start()
        try:
            self.task.state="running"
            with patch.object(self.broker.os,"replace",side_effect=replace):self.task.save()
        finally:held.close();reader.join(2)
        self.assertTrue(release.is_set());self.assertIn(5,seen)
        self.assertEqual(json.loads(path.read_text())["state"],"running")


    def test_windows_other_permission_code_is_not_retried(self):
        with patch.object(self.broker.sys,"platform","win32"), \
             patch.object(self.broker.os,"replace",side_effect=self.denial(999)) as replace, \
             patch.object(self.broker.time,"sleep") as pause, \
             self.assertRaises(PermissionError):
            self.task.save()
        replace.assert_called_once();pause.assert_not_called()
        self.assertEqual(list(self.task.directory.glob("task.json.tmp-*")),[])
