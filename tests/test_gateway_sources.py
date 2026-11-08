import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from gateway_sources import gateway_sources, gateway_sources_sha256

class GatewaySourceTests(unittest.TestCase):
    def test_on_demand_launcher_is_packaged_and_changes_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp) / 'scripts'
            scripts.mkdir()
            (scripts / 'auth_proxy.js').write_text("require('./jupyter_on_demand')", encoding='utf-8')
            (scripts / 'jupyter_on_demand.js').write_text('module.exports={}', encoding='utf-8')
            launcher = scripts / 'jupyter_launcher.py'
            launcher.write_text('print(1)', encoding='utf-8')
            first = gateway_sources(Path(tmp))
            self.assertIn('jupyter_launcher.py', first)
            launcher.write_text('print(2)', encoding='utf-8')
            self.assertNotEqual(gateway_sources_sha256(first), gateway_sources_sha256(gateway_sources(Path(tmp))))

    def test_missing_fixed_launcher_refuses_before_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp) / 'scripts'
            scripts.mkdir()
            (scripts / 'auth_proxy.js').write_text("require('./jupyter_on_demand')", encoding='utf-8')
            (scripts / 'jupyter_on_demand.js').write_text('module.exports={}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'jupyter_launcher.py'):
                gateway_sources(Path(tmp))

    def test_public_gateway_includes_fixed_launcher(self):
        source = gateway_sources(ROOT)
        self.assertTrue({'jupyter_on_demand.js', 'jupyter_launcher.py'} <= source.keys())

    def test_missing_dependency_refuses_before_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp) / "scripts"
            scripts.mkdir()
            (scripts / "auth_proxy.js").write_text("require('./missing')", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Missing regular"):
                gateway_sources(Path(tmp))

    def test_helper_change_changes_bundle_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp) / "scripts"
            scripts.mkdir()
            (scripts / "auth_proxy.js").write_text("require('./helper')", encoding="utf-8")
            (scripts / "helper.js").write_text("module.exports=1", encoding="utf-8")
            before = gateway_sources_sha256(gateway_sources(Path(tmp)))
            (scripts / "helper.js").write_text("module.exports=2", encoding="utf-8")
            self.assertNotEqual(before, gateway_sources_sha256(gateway_sources(Path(tmp))))

    def test_nested_path_requires_explicit_layout_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp) / "scripts"
            scripts.mkdir()
            (scripts / "auth_proxy.js").write_text("require('./nested/helper')", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                gateway_sources(Path(tmp))


    def test_gateway_projection_omits_controller_planner_without_mutating_source(self):
        from gateway_sources import gateway_configmap_items
        source = {'auth_proxy.js': 'gateway', 'jupyter_launcher.py': 'launcher',
                  'capacity_planner.py': 'controller-only'}
        before = dict(source)
        items = gateway_configmap_items(source)
        self.assertEqual(items, [{'key':'auth_proxy.js','path':'auth_proxy.js'},
                                {'key':'jupyter_launcher.py','path':'jupyter_launcher.py'}])
        self.assertEqual(source, before)
        for bad in [{}, {'auth_proxy.js':'ok','../bad':'no'}]:
            with self.assertRaises(ValueError): gateway_configmap_items(bad)

if __name__ == "__main__":
    unittest.main()
