import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

os.environ.setdefault('DSH_ENVIRONMENT','secure')
spec=importlib.util.spec_from_file_location('capacity_exporter',Path(__file__).parents[1]/'container/capacity-token-exporter.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


@unittest.skipUnless(os.name=='posix','Linux nonblocking descriptor checks')
class ExporterTests(unittest.TestCase):
    def test_projection_omits_command_bodies_and_unknown_fields(self):
        with tempfile.TemporaryDirectory()as tmp:
            file=Path(tmp)/'status.json';observed=time.time()
            file.write_text(json.dumps({'observedAt':observed,'services':[{'name':'jupyter','phase':'running','argv':['sensitive command'],'secret':'not projected'}]}))
            self.assertEqual(module.status_projection(file),{'observedAt':observed,'services':[{'name':'jupyter','phase':'running'}]})
    def test_fifo_symlink_oversize_invalid_and_stale_are_denied(self):
        with tempfile.TemporaryDirectory()as tmp:
            file=Path(tmp)/'status.json'
            for value in [None,{'observedAt':0,'services':[]},{'observedAt':time.time(),'services':[None]},'x'*65537]:
                file.write_text(json.dumps(value))
                with self.assertRaises((ValueError,TypeError)):module.status_projection(file)
            link=Path(tmp)/'link';link.symlink_to(file)
            with self.assertRaises(OSError):module.status_projection(link)
            fifo=Path(tmp)/'fifo';os.mkfifo(fifo);started=time.monotonic()
            with self.assertRaises(ValueError):module.status_projection(fifo)
            self.assertLess(time.monotonic()-started,1)

if __name__=='__main__':unittest.main()
