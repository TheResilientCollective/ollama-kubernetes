# S3 Reader: IAM Roles Anywhere for Kubernetes Outside AWS

## Overview

This document describes how to securely read large files from AWS S3 buckets in a Kubernetes cluster running **outside AWS** (e.g., on-premises, in another cloud, or edge infrastructure) using [IAM Roles Anywhere](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/) and [rclone](https://rclone.org/s3/).

This approach:
- Uses **short-lived, automatically rotated X.509 certificates** instead of long-term AWS access keys
- Follows AWS's official reference architecture for non-AWS workloads
- Supports multiple nodes and horizontal scaling
- Is optimized for high-bandwidth reads of large (GB+) files
- Eliminates permanent credential exposure

---

## Architecture

```
┌─────────────────────────────────────────┐
│              Kubernetes Pod             │
│                                         │
│  ┌────────────┐    ┌──────────────────┐ │
│  │  App       │    │ AWS Signing      │ │
│  │ (rclone)   │◄──►│ Helper (IMDS     │ │
│  │            │    │  serve mode)     │ │
│  └────────────┘    │  :9911           │ │
│                     └──────────────────┘ │
│           ▲                             │
│           │ Env: AWS_EC2_METADATA_      │
│  ┌────────┴───────────────────────────┐ │
│  │  Mounted: /etc/s3-cert/             │ │
│  │  (Ephemeral per-pod cert from      │ │
│  │   cert-manager CSI driver)         │ │
│  └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

Each pod gets:
1. A **per-pod ephemeral X.509 certificate** issued by cert-manager (via self-signed CA or Vault)
2. **IAM Roles Anywhere temporary credentials** via the `aws_signing_helper` sidecar
3. **Read-only S3 access** through rclone using the IMDS-compatible credential endpoint

The AWS PCA CA (`arn:aws:acm-pca:us-west-2:490004653742:certificate-authority/1abcf1bd-2b6f-43f0-8ff0-6aa6f86bfe43`) is registered as the trust anchor in IAM Roles Anywhere.

---

## Phase 1: AWS Setup

### Step 1: Create Certificate Authority (CA)

Use AWS Private CA, your organization's internal CA, or Vault to create a CA that can sign certificates for IAM Roles Anywhere.

If using AWS Private CA:
```bash
# Create a private CA for IAM Roles Anywhere
aws acm-pca create-certificate-authority \
    --certificate-authority \
        CertificateAuthorityName="iam-roles-anywhere-ca",
        Type="ROOT",
        KeyAlgorithm="RSA_2048",
    --tags TagKey=Name,TagValue=iam-roles-anywhere-ca
```

### Step 2: Register Trust Anchor in IAM Roles Anywhere

1. Go to **IAM Roles Anywhere** → **Trust anchors** → **Create trust anchor**
2. Upload your CA certificate (from AWS Private CA or your internal CA)
3. Note the **Trust Anchor ARN** (e.g., `arn:aws:rolesanywhere:us-east-1:123456789012:trust-anchor/abc-123`)

### Step 3: Create IAM Role with S3 Read Permissions

Create an IAM role with the permissions your pods need:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::your-bucket",
        "arn:aws:s3:::your-bucket/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "s3:GetObjectVersion",
      "Resource": "arn:aws:s3:::your-bucket/*"
    }
  ]
}
```

### Step 4: Create IAM Roles Anywhere Profile

1. Go to **IAM Roles Anywhere** → **Profiles** → **Create profile**
2. Attach the IAM role created in Step 3
3. Set **Session duration** (default 1 hour; max 12 hours)
4. Enable **Allow custom role session name**
5. Note the **Profile ARN**

### Step 5: Configure Trust Policy on IAM Role

Set the trust policy to allow IAM Roles Anywhere to assume the role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "rolesanywhere.amazonaws.com"
      },
      "Action": [
        "sts:TagSession",
        "sts:SetSourceIdentity",
        "sts:AssumeRole"
      ],
      "Condition": {
        "ArnEquals": {
          "aws:SourceArn": "arn:aws:rolesanywhere:<region>:<account>:trust-anchor/<trust-anchor-id>"
        }
      }
    }
  ]
}
```

### Step 6: (Optional) Enable S3 Transfer Acceleration

For better performance reading large files over long distances:

```bash
aws s3api put-bucket-accelerate-configuration \
    --bucket your-bucket \
    --accelerate-configuration Status=Enabled
```

---

## Phase 2: Kubernetes Cluster Setup

### Step 1: Install cert-manager

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml

# Wait for deployment
kubectl rollout status deployment/cert-manager -n cert-manager --timeout=180s
```

### Step 2: Install cert-manager CSI Driver

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update
helm install cert-manager-csi-driver jetstack/cert-manager-csi-driver \
  --namespace cert-manager \
  --create-namespace

# Verify
kubectl get pods -n cert-manager
```

### Step 3: Configure Certificate Authority for cert-manager

Since we are using **AWS Private CA** (ARN: `arn:aws:acm-pca:us-west-2:490004653742:certificate-authority/1abcf1bd-2b6f-43f0-8ff0-6aa6f86bfe43`), we need to configure cert-manager to issue certificates signed by this CA.

**Option A: Self-Signed Issuer (Simplest)**

If your AWS PCA CA certificate is available, you can create a self-signed issuer that acts as the root, then an intermediate issuer pointing to AWS PCA:

```bash
# Download your AWS PCA CA certificate
aws acm-pca get-certificate-authority-certificate \
    --certificate-authority-arn arn:aws:acm-pca:us-west-2:490004653742:certificate-authority/1abcf1bd-2b6f-43f0-8ff0-6aa6f86bfe43 \
    --output json | jq -r '.Certificate' > pca-ca.crt
```

```yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: s3-reader-selfsigned-issuer
  namespace: default
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: s3-reader-intermediate-ca
  namespace: default
spec:
  isCA: true
  commonName: "s3-reader-issuer"
  secretName: s3-reader-intermediate-ca-secret
  duration: 8760h # 1 year
  renewBefore: 720h # 30 days
  issuerRef:
    name: s3-reader-selfsigned-issuer
    kind: Issuer
---
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: s3-reader-issuer
  namespace: default
spec:
  ca:
    secretName: s3-reader-intermediate-ca-secret
```

**Option B: Vault as Signing Intermediary (If already running)**

If you have an existing Vault cluster, you can configure it to sign certificates using the AWS PCA private CA:

```bash
# Enable PKI secrets engine and configure to use AWS PCA
kubectl exec vault-0 -- vault secrets enable pki
kubectl exec vault-0 -- vault write pki/config/urls \
    issuing_certificates="https://your-vault-url/v1/pki/ca" \
    crl_distribution_points="https://your-vault-url/v1/pki CRL"
kubectl exec vault-0 -- vault write pki/roles/iam-roles-anywhere \
    allowed_domains="s3-reader.default.svc, s3-reader.default.svc.cluster.local" \
    allow_subdomains=true \
    allow_bare_domains=true \
    max_ttl=24h \
    ttl=24h
```

```yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: s3-reader-vault-issuer
  namespace: default
spec:
  vault:
    server: "https://vault.default.svc.cluster.local:8200"
    path: "pki_int/sign/iam-roles-anywhere"
    caBundle: |
      -----BEGIN CERTIFICATE-----
      <Vault intermediate CA certificate>
      -----END CERTIFICATE-----
    auth:
      tokenSecretRef:
        name: "vault-secret"
        key: "token"
```

```bash
# Create secret for Vault authentication token (only needed for Option B)
kubectl create secret generic vault-secret \
    --from-literal=token="<your-vault-token>" \
    -n default
```

---

## Phase 3: Application Deployment

### Step 4: Create Certificate Resource

The `Certificate` resource is required by the cert-manager CSI driver to know what certificate to issue. This was missing from the original deployment.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: s3-reader-cert
  namespace: default
spec:
  secretName: s3-reader-cert-secret
  duration: 24h
  renewBefore: 3h
  dnsNames:
    - s3-reader
    - s3-reader.default.svc
    - s3-reader.default.svc.cluster.local
  issuerRef:
    name: s3-reader-issuer
    kind: Issuer
```

**Important:** The `duration: 24h` and `renewBefore: 3h` settings align with:
- IAM Roles Anywhere profile session duration (default 1 hour, max 12 hours)
- Vault PKI role TTL (if using Option B)
- cert-manager CSI driver automatic renewal before expiry

### Deployment Manifest

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: s3-reader
  namespace: default
  labels:
    app: s3-reader
spec:
  replicas: 1
  selector:
    matchLabels:
      app: s3-reader
  template:
    metadata:
      labels:
        app: s3-reader
    spec:
      # Pod-level security context
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault

      initContainers:
      # Wait for certificate to be mounted by cert-manager CSI driver
      - name: wait-for-cert
        image: busybox:1.36.1
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop: ["ALL"]
          runAsNonRoot: true
          runAsUser: 1000
          runAsGroup: 1000
        command:
          - /bin/sh
          - -c
          - |
            echo "Waiting for certificate to be mounted..."
            until [ -f /etc/s3-cert/tls.crt ] && [ -f /etc/s3-cert/tls.key ]; do
              sleep 1
            done
            echo "Certificate mounted successfully."
            openssl x509 -in /etc/s3-cert/tls.crt -noout -subject -dates
        volumeMounts:
          - name: s3-cert
            mountPath: /etc/s3-cert
            readOnly: true

      containers:
      # Main application container (rclone for large file downloads)
      - name: reader
        image: rclone/rclone:latest
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop: ["ALL"]
        env:
          # Redirect AWS SDK IMDS calls to local signing helper sidecar
          - name: AWS_EC2_METADATA_SERVICE_ENDPOINT
            value: "http://127.0.0.1:9911/"
          - name: AWS_REGION
            value: "us-east-1"
        command: ["/bin/sh", "-c"]
        args:
          - |
            # Wait for signing helper to be ready
            echo "Starting S3 download..."
            rclone copy s3-accelerated:your-bucket/large-file.bin /cache/ \
              --transfers 4 \
              --s3-chunk-size 64M \
              --s3-upload-concurrency 4 \
              --s3-use-accelerate-endpoint \
              --multi-thread-cutoff 64M \
              --buffer-size 64M \
              --log-level INFO
        volumeMounts:
          - name: s3-cert
            mountPath: /etc/s3-cert
            readOnly: true
          - name: cache
            mountPath: /cache

      # AWS Signing Helper sidecar (IMDS serve mode)
      - name: aws-signing-helper
        image: public.ecr.aws/rolesanywhere/aws-signing-helper:v1.8.5
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop: ["ALL"]
        args:
          - serve
          - --certificate
          - /etc/s3-cert/tls.crt
          - --private-key
          - /etc/s3-cert/tls.key
          - --profile-arn
          - arn:aws:rolesanywhere:<region>:<account>:profile/<profile-id>
          - --role-arn
          - arn:aws:iam::<account>:role/<role-name>
          - --trust-anchor-arn
          - arn:aws:rolesanywhere:<region>:<account>:trust-anchor/<trust-anchor-id>
          - --listen
          - 127.0.0.1:9911
        ports:
          - containerPort: 9911
            name: imds
        volumeMounts:
          - name: s3-cert
            mountPath: /etc/s3-cert
            readOnly: true
        # Readiness probe: TCP socket check (IMDSv2 requires token auth, so httpGet returns 401)
        readinessProbe:
          tcpSocket:
            port: 9911
          initialDelaySeconds: 2
          periodSeconds: 5
          timeoutSeconds: 2
        # Liveness probe: TCP socket check
        livenessProbe:
          tcpSocket:
            port: 9911
          initialDelaySeconds: 10
          periodSeconds: 30
          timeoutSeconds: 2

      volumes:
        # Ephemeral per-pod certificate via cert-manager CSI driver
        - name: s3-cert
          csi:
            driver: "csi.cert-manager.io"
            readOnly: true
            volumeAttributes:
              csi.cert-manager.io/issuer-name: "s3-reader-issuer"
              csi.cert-manager.io/issuer-kind: "Issuer"
              csi.cert-manager.io/alt-names: "s3-reader"
              csi.cert-manager.io/dns-names: "s3-reader"
        - name: cache
          emptyDir: {}
```

---

## Phase 4: NetworkPolicy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: s3-reader-network-policy
  namespace: default
spec:
  podSelector:
    matchLabels:
      app: s3-reader
  policyTypes:
  - Egress
  egress:
    # Allow DNS resolution
    - to:
        - namespaceSelector:
            matchLabels:
              name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
    # Allow egress to AWS endpoints (including S3 Transfer Acceleration edge locations)
    # WARNING: S3 Transfer Acceleration uses global CloudFront edge locations.
    # The 0.0.0.0/0 below is intentionally broad because:
    # 1. IAM Roles Anywhere STS calls go to global endpoints
    # 2. S3 Transfer Acceleration endpoints resolve to edge locations that can be anywhere in AWS
    # 
    # CRITICAL FOR PRODUCTION: Replace 0.0.0.0/0 with actual AWS IP ranges:
    # 
    # Download AWS IP ranges:
    # curl -s https://ip-ranges.amazonaws.com/ip-ranges.json | jq '.prefixes[].ip_prefix' | sort -u
    #
    # Or better yet: Use VPC endpoints / PrivateLink where possible for:
    # - S3: com.amazonaws.<region>.s3
    # - STS: com.amazonaws.<region>.sts
    # This confines traffic to AWS private IPs and provides better security control
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - protocol: TCP
          port: 443
      except:
        - 10.0.0.0/8  # Cluster private IPs
        - 172.16.0.0/12
        - 192.168.0.0/16
```

---

## Phase 5: Certificate Rotation

### Approach Options

#### Option A: Short-Lived Certificates (Recommended)

Configure certificates with 24-hour TTL (matching the IAM Roles Anywhere profile session duration). The cert-manager CSI driver will automatically renew them before expiry (configured via `renewBefore: 3h` in the `Certificate` resource).

The `aws_signing_helper` in serve mode handles credential renewal transparently — it polls IAM Roles Anywhere for new temporary credentials using the certificate before expiration. This means the application (rclone) does not need to handle certificate reloads directly.

For applications that don't auto-reload certificates:
```yaml
# Add cert-reloader sidecar to watch certificate changes (if needed for your app)
- name: cert-reloader
  image: quay.io/prometheus/certs-reloader:v0.73.0
  args:
    - --watch
    - --cert-dir=/etc/s3-cert
    - --resync=0
  volumeMounts:
    - name: s3-cert
      mountPath: /etc/s3-cert
      readOnly: true
```

#### Option B: Short-Pod Lifetime

If pods run as short-lived jobs (e.g., batch processing), certificate rotation isn't needed. Pods terminate before certificates expire.

---

## Monitoring and Verification

### Health Checks

```bash
# 1. Check pod status and readiness
kubectl get pods -l app=s3-reader
kubectl describe pod -l app=s3-reader

# 2. Verify signing helper is listening
kubectl exec <pod-name> -c aws-signing-helper -- \
  curl -s --connect-timeout 2 http://127.0.0.1:9911/latest/meta-data/ > /dev/null && echo "OK"

# 3. Verify certificate was mounted correctly
kubectl exec <pod-name> -c aws-signing-helper -- \
  openssl x509 -in /etc/s3-cert/tls.crt -noout -subject -dates

# 4. Check rclone logs for successful S3 access
kubectl logs <pod-name> -c reader

# 5. Verify certificate issuance
kubectl get certificate -n default
kubectl describe certificate s3-reader-cert -n default

# 6. Verify credentials via IMDS (using signing helper's own endpoint)
kubectl exec <pod-name> -c aws-signing-helper -- \
  /usr/local/bin/aws-signing-helper credential-process --profile-arn \
  arn:aws:rolesanywhere:<region>:<account>:profile/<profile-id> \
  --role-arn arn:aws:iam::<account>:role/<role-name> \
  --trust-anchor-arn arn:aws:rolesanywhere:<region>:<account>:trust-anchor/<trust-anchor-id>
```

### Alerting Rules (Prometheus)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: s3-reader-alerts
  namespace: default
spec:
  groups:
  - name: s3-reader
    rules:
    - alert: SigningHelperUnreachable
      expr: probe_success{job="s3-reader"} == 0
      for: 1m
      labels:
        severity: critical
      annotations:
        summary: "AWS Signing Helper sidecar is not responding"
        description: "Cannot connect to IMDS endpoint on port 9911"
    - alert: CertificateExpiration
      expr: (kube_certificate_expiration_timestamp - time()) / 3600 < 1
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "S3 reader certificate expiring soon"
        description: "Certificate will expire in less than 1 hour"
```

---

## Security Considerations

### Key Security Properties

1. **No permanent AWS credentials** - Uses short-lived role assumption via X.509 certs
2. **Per-pod certificates** - Each pod gets its own ephemeral cert
3. **Read-only access** - IAM role scoped to S3 read operations only
4. **Least privilege** - Pod security context restricts privileges
5. **Encrypted transport** - All S3 communication over HTTPS

### Important Security Notes

- **IMDS endpoint security**: The signing helper listens on `127.0.0.1:9911` - any process in the pod that can reach loopback can obtain AWS credentials. Within Kubernetes, all containers in a pod share loopback. To mitigate, minimize the number of containers in the pod.
- **Certificate lifecycle**: Certificates are automatically renewed by cert-manager before expiry. The `aws_signing_helper` handles credential refresh transparently using the updated certificate.
- **Network isolation**: Use NetworkPolicy to restrict egress to only necessary AWS endpoints. See NetworkPolicy section for details on S3 Transfer Acceleration endpoint requirements.
- **Source IP restriction**: **Cannot be used** with IAM Roles Anywhere because STS calls originate from AWS edge locations, not your Kubernetes nodes.

---

## Troubleshooting

### Common Issues

#### Pod stays in Pending
- Verify cert-manager and CSI driver are running: `kubectl get pods -n cert-manager`
- Check that the `Certificate` resource exists: `kubectl get certificate -n default`
- Check cert-manager controller logs: `kubectl logs -n cert-manager deploy/cert-manager`

#### Signing Helper fails to start
- Verify the init container completed successfully: `kubectl logs <pod-name> -c wait-for-cert`
- Check certificate and key file mounts exist: `kubectl exec -c aws-signing-helper -- ls -la /etc/s3-cert/`
- Verify all ARN parameters are correct (trust anchor, profile, role)
- Check Vault/AWS PCA CA is issuing certificates and hasn't expired

#### rclone cannot access S3
- Confirm `AWS_EC2_METADATA_SERVICE_ENDPOINT` is set correctly
- Verify IAM role has proper S3 permissions
- Test credentials via IMDS endpoint: `kubectl exec -c aws-signing-helper -- curl -s http://127.0.0.1:9911/latest/meta-data/` (IMDSv2 requires token; use tcpSocket readiness probe)
- Check rclone logs for specific error messages: `kubectl logs <pod-name> -c reader`
- Verify S3 bucket name and region match your configuration

#### Certificate not renewing
- Verify cert-manager and CSI driver are running: `kubectl get pods -n cert-manager`
- Check certificate status: `kubectl describe certificate s3-reader-cert -n default`
- Ensure the `duration` and `renewBefore` fields are set correctly in the `Certificate` resource
- If using AWS PCA as CA, verify the CA certificate hasn't expired and can still sign certificates

---

## Cost Considerations

1. **AWS IAM Roles Anywhere**: Pay-per-use ($0.04 per 1000 certificate validation requests)
2. **S3 requests**: $0.005 per 1000 GET/HEAD requests
3. **Data transfer**: Standard S3 egress pricing applies (reduced rates with Transfer Acceleration)
4. **Certificate management**: Vault/ACM PCA costs apply if using AWS services
5. **Kubernetes**: No additional costs beyond standard compute/storage

---

## References

- [AWS IAM Roles Anywhere User Guide](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/)
- [cert-manager CSI Driver Documentation](https://github.com/cert-manager/csi-driver)
- [rclone S3 Backend Documentation](https://rclone.org/s3/)
- [AWS Blog: Extend IAM roles to workloads in multicloud with AWS IAM Roles Anywhere](https://aws.amazon.com/blogs/security/extend-iam-roles-to-workloads-in-multicloud-with-aws-iam-roles-anywhere/)