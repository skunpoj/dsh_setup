"""Public CI roots use the same authority builder; private release defaults remain separate."""
import importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('manual',ROOT/'scripts/build_manual_bundle.py')
manual=importlib.util.module_from_spec(spec);spec.loader.exec_module(manual)

class PublicManualEntrypointsTests(unittest.TestCase):
    def test_public_selection_is_explicit_sorted_and_not_a_private_default(self):
        names=json.loads((ROOT/'.github/public-manual-entrypoints.json').read_text(encoding='utf-8'))
        self.assertEqual(names,sorted(names));self.assertEqual(manual.validate_entrypoints(names),names)
        self.assertTrue({'index.html','DSH_PLATFORM_GUIDE.html','HARNESS_TERMINOLOGY.html'}<=set(names))
        self.assertNotIn('DSH_GUIDED_TOUR.html',names)
        self.assertTrue(all('/' not in name and name.endswith('.html') for name in names))
        for name in names:
            self.assertNotIn(Path(name).stem.casefold(),manual.INTERNAL_RUNBOOK_STEMS)

    def test_actual_cli_packages_every_selected_root_and_closes_asset_links(self):
        names=json.loads((ROOT/'.github/public-manual-entrypoints.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);(home/'docs').mkdir();(home/'scripts').mkdir();(home/'.github').mkdir()
            script=home/'scripts/build_manual_bundle.py';script.write_bytes((ROOT/'scripts/build_manual_bundle.py').read_bytes())
            selection=home/'.github/public-manual-entrypoints.json';selection.write_bytes((ROOT/'.github/public-manual-entrypoints.json').read_bytes())
            for name in names:(home/'docs'/name).write_bytes(('<p>'+name+'</p><img src="asset.svg">').encode())
            (home/'docs/asset.svg').write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
            (home/'docs/COURSE_GUIDE.md').write_bytes(b'Unselected retained private default')
            run=subprocess.run([sys.executable,str(script),'--output',str(home/'bundle'),'--entrypoints-json',str(selection)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            manifest=json.loads((home/'bundle/manifest.json').read_text())
            self.assertEqual(set(manifest['files']),set(names)|{'asset.svg'})
            self.assertEqual(json.loads(run.stdout)['files'],len(names)+1)
            for name in manifest['files']:self.assertEqual((home/'bundle'/name).read_bytes(),(home/'docs'/name).read_bytes())

if __name__=='__main__':unittest.main()
