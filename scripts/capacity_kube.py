"""Small in-cluster Kubernetes client. No shell, exec, or arbitrary proxy API."""
import json
import hashlib
import os
from pathlib import Path
import re
import ssl
import urllib.error
import urllib.request

KINDS = {
    'Deployment': ('/apis/apps/v1', 'deployments'),
    'Service': ('/api/v1', 'services'),
    'Secret': ('/api/v1', 'secrets'),
    'PersistentVolumeClaim': ('/api/v1', 'persistentvolumeclaims'),
    'Pod': ('/api/v1', 'pods'),
    'Job': ('/apis/batch/v1', 'jobs'),
    'Node': ('/api/v1', 'nodes'),
    'AllPod': ('/api/v1', 'pods'),
    'StorageCapacity': ('/apis/storage.k8s.io/v1', 'csistoragecapacities'),
    'NodeMetrics': ('/apis/metrics.k8s.io/v1beta1', 'nodes'),
}


class Kube:
    def __init__(self, namespace, token_file='/var/run/secrets/kubernetes.io/serviceaccount/token',
                 ca_file='/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'):
        if not re.fullmatch(r'[a-z0-9-]{1,63}', namespace):
            raise ValueError('Invalid namespace')
        self.namespace = namespace
        self.token_file = Path(token_file)
        self.base = 'https://' + os.environ['KUBERNETES_SERVICE_HOST'] + ':' + os.environ.get('KUBERNETES_SERVICE_PORT', '443')
        self.tls = ssl.create_default_context(cafile=ca_file)

    def call(self, method, kind, name=None, body=None, selector=None):
        prefix, plural = KINDS[kind]
        url = self.base + prefix + ('' if kind in ['Node', 'AllPod', 'StorageCapacity', 'NodeMetrics'] else '/namespaces/' + self.namespace) + '/' + plural
        if name:
            if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,251}', name):
                raise ValueError('Invalid resource name')
            url += '/' + name
        if selector:
            from urllib.parse import urlencode
            url += '?' + urlencode({'labelSelector': selector})
        headers = {'Authorization': 'Bearer ' + self.token_file.read_text().strip(), 'Content-Type': 'application/json'}
        req = urllib.request.Request(url, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, context=self.tls, timeout=25) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404 and method == 'GET':
                return None
            # Kubernetes bodies can include supplied values; never log them.
            raise RuntimeError('Kubernetes ' + method + ' ' + kind + ': HTTP ' + str(error.code)) from None

    def scale(self, name, replicas):
        # Only private user runtimes may be started or stopped, and only to 0
        # or 1. Scaling never edits the template, storage or credentials.
        if not re.fullmatch(r'dsh-u-[0-9a-f]{16}-(secure|internet)', name) or replicas not in (0, 1):
            raise ValueError('Refusing to scale outside private user runtimes')
        url = self.base + '/apis/apps/v1/namespaces/' + self.namespace + '/deployments/' + name + '/scale'
        headers = {'Authorization': 'Bearer ' + self.token_file.read_text().strip(),
                   'Content-Type': 'application/merge-patch+json'}
        req = urllib.request.Request(url, method='PATCH', headers=headers,
                                     data=json.dumps({'spec': {'replicas': replicas}}).encode())
        try:
            with urllib.request.urlopen(req, context=self.tls, timeout=25) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError('Kubernetes PATCH scale: HTTP ' + str(error.code)) from None

    def ensure_new(self, document):
        kind, name = document['kind'], document['metadata']['name']
        if not name.startswith(('dsh-cap-', 'dsh-u-', 'dsh-inference-signup-', 'dsh-harness-signup-', 'dsh-app-status-')):
            raise ValueError('Refusing to write outside provisioner resource prefixes')
        fingerprint=hashlib.sha256(json.dumps({k:document[k]for k in ['kind','spec','data','type']if k in document},sort_keys=True).encode()).hexdigest()
        old = self.call('GET', kind, name)
        if old:
            if (old['metadata'].get('labels', {}).get('dsh.example.com/capacity-managed') != 'true' or
                old['metadata'].get('annotations',{}).get('dsh.example.com/capacity-spec-sha256')!=fingerprint):
                raise ValueError('Existing object is not owned by the provisioner')
            return old
        document['metadata'].setdefault('labels', {})['dsh.example.com/capacity-managed'] = 'true'
        document['metadata'].setdefault('annotations', {})['dsh.example.com/capacity-spec-sha256']=fingerprint
        document['metadata']['namespace'] = self.namespace
        return self.call('POST', kind, body=document)
