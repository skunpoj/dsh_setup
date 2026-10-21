import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('public_gate',ROOT/'scripts/check_public_release.py')
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)

class PublicReleaseGateTests(unittest.TestCase):
 def test_missing_root_is_not_a_clean_scan(self):
  with TemporaryDirectory() as t:
   with self.assertRaises(ValueError):gate.scan(Path(t)/'missing')
 def test_personal_path_is_rejected_without_echoing_value(self):
  with TemporaryDirectory() as t:
   p=Path(t);(p/'note.txt').write_text('C:'+chr(92)+'Users'+chr(92)+'private-owner'+chr(92)+'file')
   findings=gate.scan(p);self.assertEqual(findings,[{'path':'note.txt','kind':'personal-path'}])
 def test_presentation_notes_are_inspected(self):
  with TemporaryDirectory() as t:
   p=Path(t)
   with ZipFile(p/'talk.pptx','w') as z:z.writestr('ppt/notesSlides/notesSlide1.xml','private-deployment-marker')
   self.assertEqual(gate.scan(p,['private-deployment-marker'])[0]['kind'],'private-site-term')
 def test_links_and_metadata_are_inspected(self):
  with TemporaryDirectory() as t:
   p=Path(t)
   with ZipFile(p/'talk.pptx','w') as z:z.writestr('docProps/core.xml','private-deployment-marker')
   self.assertEqual(len(gate.scan(p,['private-deployment-marker'])),1)
 def test_clean_example_passes(self):
  with TemporaryDirectory() as t:
   p=Path(t);(p/'note.txt').write_text('https://workspace.example.com; supplied by the operator')
   self.assertEqual(gate.scan(p),[])

if __name__=='__main__':unittest.main()
