import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class KubectlBoundaryTests(unittest.TestCase):
    def test_runtime_image_pins_and_verifies_kubectl(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("ARG KUBECTL_VERSION=v1.32.9", dockerfile)
        self.assertIn("KUBECTL_LINUX_AMD64_SHA256=509ae171", dockerfile)
        self.assertIn("sha256sum -c -", dockerfile)
        self.assertIn("kubectl version --client=true", dockerfile)

    def test_workspace_manifests_do_not_mount_cluster_identity(self):
        manifests = list((ROOT / "k8s").glob("*.yaml"))
        self.assertTrue(manifests)
        pools = (ROOT / "k8s" / "dsh-environment-pools.yaml").read_text(encoding="utf-8")
        self.assertIn("automountServiceAccountToken: false", pools)
        self.assertNotIn("kind: ClusterRoleBinding", pools)
        self.assertNotIn("kind: RoleBinding", pools)


if __name__ == "__main__":
    unittest.main()
