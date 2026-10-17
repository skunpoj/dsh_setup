import unittest
from pathlib import Path
import yaml


class LegacyContainmentTests(unittest.TestCase):
    def test_policy_is_scoped_and_retains_required_services(self):
        p = yaml.safe_load((Path(__file__).parents[1]/'k8s/dsh-legacy-containment.yaml').read_text())['spec']
        self.assertEqual(p['podSelector']['matchExpressions'][0]['values'], ['dsh-user2', 'dsh3'])
        self.assertEqual(p['policyTypes'], ['Ingress', 'Egress'])
        self.assertEqual(p['ingress'][0]['ports'], [{'protocol': 'TCP', 'port': 3080}])
        self.assertIn('podSelector', p['ingress'][0]['from'][0])
        ports = {item['port'] for rule in p['egress'] for item in rule.get('ports', [])}
        self.assertTrue({4000, 53, 88, 28998}.issubset(ports))
        public = next(r['to'][0]['ipBlock'] for r in p['egress'] if r.get('to', [{}])[0].get('ipBlock', {}).get('cidr') == '0.0.0.0/0')
        self.assertTrue({'10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'}.issubset(public['except']))

    def test_bootstrap_does_not_reseed_factory_passwords(self):
        for name in ['dsh2-deployment.yaml', 'dsh3-deployment.yaml']:
            source = (Path(__file__).parents[1]/'k8s'/name).read_text()
            self.assertNotIn('AUTH_PASS=', source)
            self.assertNotIn('name: AUTH_PASS', source)
            d = yaml.safe_load(source)['spec']['template']['spec']
            self.assertFalse(d['automountServiceAccountToken'])
            worker = next(c for c in d['containers'] if c['name']=='dsh')
            self.assertEqual(worker['securityContext']['runAsUser'],10001)
            self.assertFalse(any(m['name']=='legacy-auth' for m in worker['volumeMounts']))
            self.assertTrue(any(c['name']=='auth-proxy' for c in d['containers']))
            self.assertTrue(any(c['name']=='audit-exporter' for c in d['containers']))


if __name__ == '__main__': unittest.main()
