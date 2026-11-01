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

    def test_workspace_examples_do_not_mount_cluster_identity(self):
        manifests = list((ROOT / "k8s" / "example").glob("*.yaml"))
        self.assertTrue(manifests)
        private_users = (ROOT / "k8s" / "example" / "50-private-users.yaml").read_text(encoding="utf-8")
        self.assertIn("automountServiceAccountToken: false", private_users)
        self.assertNotIn("kind: ClusterRoleBinding", private_users)
        self.assertNotIn("kind: RoleBinding", private_users)


if __name__ == "__main__":
    unittest.main()
