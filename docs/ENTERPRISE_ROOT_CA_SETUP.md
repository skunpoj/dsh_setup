# Enterprise Root CA & SSL Inspection Setup Guide

In enterprise corporate environments, outbound and internal HTTPS traffic is often routed through corporate proxy firewalls, API gateways, or internal ingress controllers that use internal enterprise Public Key Infrastructure (PKI) certificates.

When running containers like **DeepSeek Harness (DSH)** on Ubuntu 24.04 inside such networks, tools like `git`, `curl`, `pip`, and `npm` will reject HTTPS connections with self-signed certificate errors (e.g., `unable to get local issuer certificate`, `CERT_HAS_EXPIRED`, or `SSL: CERTIFICATE_VERIFY_FAILED`).

This guide details how to properly configure, mount, and trust custom enterprise Root CA certificates in your DSH deployment.

---

## 🏛️ Architecture & Verification Chain

```
┌────────────────────────────────────────────────────────┐
│              Enterprise Network / Ingress              │
│       TLS Certificate signed by Enterprise Root CA     │
└───────────────────────────┬────────────────────────────┘
                            │ HTTPS Handshake
                            ▼
┌────────────────────────────────────────────────────────┐
│             DSH Container (Ubuntu 24.04)               │
│                                                        │
│  Mounted Root CA:                                      │
│  /usr/local/share/ca-certificates/enterprise-ca.crt    │
│                           │                            │
│                           ▼ update-ca-certificates    │
│  System Trust Store:                                   │
│  /etc/ssl/certs/ca-certificates.crt                    │
│                           │                            │
│   ┌───────────────────────┼────────────────────────┐   │
│   ▼                       ▼                        ▼   │
│  Curl / OpenSSL     Python (Pip/urllib)     Node.js    │
│  (System Store)     (SSL_CERT_FILE)         (NODE_     │
│                                              EXTRA_    │
│                                              CA_CERTS) │
└────────────────────────────────────────────────────────┘
```

---

## 📋 Step 1: Extract Your Enterprise Root CA

If you do not have the PEM certificate file from your PKI team, you can extract it directly from your corporate ingress or gateway using OpenSSL:

```bash
# Replace gateway.internal.corp:443 with your internal gateway or API host
echo | openssl s_client -showcerts -servername gateway.internal.corp -connect gateway.internal.corp:443 2>/dev/null \
  | awk '/BEGIN CERTIFICATE/,/END CERTIFICATE/{ if(/BEGIN CERTIFICATE/) {cert++} if(cert==2) print }' \
  > enterprise-root-ca.crt
```

> **Note**: In a 2-tier certificate chain (Server Cert -> Root CA), `cert==2` extracts the Root CA. Inspect the extracted file:
> ```bash
> openssl x509 -in enterprise-root-ca.crt -text -noout | grep -E "Issuer|Subject|Not After"
> ```

---

## 📦 Step 2: Package the Certificate as a Kubernetes ConfigMap

Create a Kubernetes ConfigMap containing your enterprise certificate(s):

```bash
kubectl create configmap enterprise-ca-certificates \
  --from-file=enterprise-root-ca.crt=./enterprise-root-ca.crt \
  -n llm
```

Or define it declaratively in YAML:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: enterprise-ca-certificates
  namespace: llm
data:
  enterprise-root-ca.crt: |
    -----BEGIN CERTIFICATE-----
    MIIDXTCCAkWgAwIBAgIJAL... [YOUR CERTIFICATE DATA] ...
    -----END CERTIFICATE-----
```

---

## ⚙️ Step 3: Mount Certificate into DSH Deployment

Edit `k8s/deployment.yaml` to mount the ConfigMap into `/usr/local/share/ca-certificates/`:

```yaml
spec:
  template:
    spec:
      volumes:
        # Existing volumes
        - name: workspace-volume
          persistentVolumeClaim:
            claimName: dsh-workspace-pvc
        - name: model-config-volume
          configMap:
            name: dsh-model-config

        # 1. Add CA volume
        - name: enterprise-ca-volume
          configMap:
            name: enterprise-ca-certificates

      containers:
        - name: dsh
          image: ubuntu:24.04
          volumeMounts:
            # Existing mounts
            - name: workspace-volume
              mountPath: /workspace
            - name: model-config-volume
              mountPath: /scripts

            # 2. Mount into Ubuntu CA directory
            - name: enterprise-ca-volume
              mountPath: /usr/local/share/ca-certificates/enterprise-root-ca.crt
              subPath: enterprise-root-ca.crt
```

The container bootstrap script in `k8s/deployment.yaml` automatically detects any certificates mounted in `/usr/local/share/ca-certificates/` and runs `update-ca-certificates`:

```bash
# Automatically executed on container startup:
if [ -d /usr/local/share/ca-certificates ] && [ -n "$(ls -A /usr/local/share/ca-certificates 2>/dev/null)" ]; then
  echo "Registering custom enterprise root CA certificates..."
  update-ca-certificates 2>/dev/null || true
fi
```

---

## 🌐 Step 4: Environment Variables for Runtimes

Ubuntu's `update-ca-certificates` generates the unified bundle at `/etc/ssl/certs/ca-certificates.crt`. To ensure all programming runtimes and tools inherit the trust store, verify or add these environment variables to the container spec in `k8s/deployment.yaml`:

```yaml
          env:
            # Python Requests / Urllib / Pip
            - name: REQUESTS_CA_BUNDLE
              value: /etc/ssl/certs/ca-certificates.crt
            - name: SSL_CERT_FILE
              value: /etc/ssl/certs/ca-certificates.crt

            # Node.js LTS Runtime
            - name: NODE_EXTRA_CA_CERTS
              value: /etc/ssl/certs/ca-certificates.crt

            # Git Global Settings
            - name: GIT_SSL_CAINFO
              value: /etc/ssl/certs/ca-certificates.crt
```

---

## ✅ Step 5: Verification Runbook

Exec into your running DSH pod and verify SSL connectivity:

```bash
POD=$(kubectl get pod -n llm -l app=dsh -o jsonpath='{.items[0].metadata.name}')

# 1. Check system CA registration
kubectl exec -n llm $POD -- ls -lh /usr/local/share/ca-certificates/

# 2. Test Curl against internal enterprise endpoint
kubectl exec -n llm $POD -- curl -I https://gateway.internal.corp

# 3. Test Python SSL verification
kubectl exec -n llm $POD -- python3 -c '
import urllib.request
resp = urllib.request.urlopen("https://gateway.internal.corp")
print("Python SSL Verification: OK, Status Code:", resp.getcode())
'

# 4. Test Node.js SSL verification
kubectl exec -n llm $POD -- node -e '
const https = require("https");
https.get("https://gateway.internal.corp", (res) => {
  console.log("Node.js SSL Verification: OK, Status Code:", res.statusCode);
});
'
```
