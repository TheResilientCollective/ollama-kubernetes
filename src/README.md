# Deployment

## SDSC Additions

Skip this section if your storage disks have decent read/write speeds.

On the San Diego Supercomputing Center, the disk read/write speeds are extremely slow, so as a work around we are using an S3 bucket on AWS for hosting the LLM models. This is done by mounting the S3 bucket as part of the file system using `rclone`. To do this without permanent credentials, we have to setup a certificate manager that refreshes keys with AWS Private Certificate Authority.

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml

# Install CSI Driver via Helm
helm repo add jetstack https://charts.jetstack.io
helm repo update
helm install cert-manager-csi-driver jetstack/cert-manager-csi-driver \
  --namespace cert-manager \
  --create-namespace
```

## Start the cluster

```bash
kubectl apply -f pvc.yaml -n ollama
kubectl apply -f configmap.yaml -n ollama
kubectl apply -f job-pull-models.yaml -n ollama
```

You may wish/need to augment each helm installation with additonal files specifying the hardward you are deploying on. For instance, at SDSC, you should add an additional `-f values-sdsc.yaml` to each of the below lines (e.g. `helm install small ./chart/ -f values-small.yaml -f values-sdsc.yaml -n ollama`)

```bash
helm install small ./chart/ -f values-small.yaml -n ollama
helm install medium ./chart/ -f values-medium.yaml -n ollama
helm install large ./chart/ -f values-large.yaml -n ollama
helm install infrastructure ./chart/ -f values-infrastructure.yaml -n ollama
```

## GPU Support

There are a few toggles to make depending on which GPU you are using:

### Nvidia

Make sure NVIDIA drivers are installed on the host machine and Kubernetes

1. Add Nvidia plugin to kubernetes

```bash
# Install NVIDIA device plugin
helm repo add nvdp https://nvidia.github.io/k8s-device-plugin
helm repo update
# On x64
helm install nvdp nvdp/nvidia-device-plugin -n nvidia-device-plugin
```

For Nvidia Jetson:

```bash
kubectl label node c4h-jetson-orin-nano-1 nvidia.com/gpu.present=true
helm install nvdp nvdp/nvidia-device-plugin \
  --namespace nvidia-device-plugin \
  --create-namespace \
  --version 0.20.1
```

Edit _/var/snap/microk8s/7988/args/containerd.toml_ and add

```toml
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.nvidia]
  runtime_type = "io.containerd.runc.v2"
  [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.nvidia.options]
    BinaryName = "nvidia-container-runtime"
```

```bash
sudo ln -sf /usr/lib/aarch64-linux-gnu/nvidia/*.so* /usr/lib/aarch64-linux-gnu/
```

```bash
kubectl get pods -n kube-system | grep nvidia
```

2. Label and taint GPU nodes:

```bash
kubectl label nodes <gpu-node-name> nvidia.com/gpu=true
kubectl taint nodes <gpu-node-name> nvidia.com/gpu:NoSchedule
```

3. Configure **chart/values.yaml** to set `.gpu.vendor` and `.gpu.tolerations.key` to the Nvidia versions. And make sure `.gpu.enabled` is `true`

### AMD

1. Add AMD plugin to kubernetes

```bash
kubectl apply -f https://raw.githubusercontent.com/ROCm/k8s-device-plugin/main/k8s-ds-amdgpu-dp.yaml
```

2. Label and taint GPU nodes:

```bash
kubectl label nodes <gpu-node-name> amd.com/gpu=true
kubectl taint nodes <gpu-node-name> amd.com/gpu:NoSchedule
```

3. Configure **chart/values.yaml** to set `.gpu.vendor` and `.gpu.tolerations.key` to the AMD versions. And make sure `.gpu.enabled` is `true`

### Apple

In **chart/values.yaml** make sure `.gpu.enabled` is `false`. Metal GPU access is automatic in OrbStack and other docker implementations.

---

## Scaling

There is a custom autoscaler implemented that you should treat as the default. For legacy support, you can still use KEDA or HPA by enabling them in **chart/values.yaml**. If you use the KEDA scaler, you will need to add KEDA and Prometheus to helm:

**KEDA**

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda \
    --namespace keda \
    --create-namespace
```

**Prometheus**

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack \
    --namespace monitoring \
    --create-namespace
```

Once this is done, you can install the helm charts for small/medium/large/router

## Port Forwarding

#### Exposing the router/gateway

This let's you send queries to ollama

```bash
kubectl port-forward -n ollama deployment/ollama-router 11434:11434
```

Now you can run

```bash
curl http://localhost:11434/api/generate -d '{"model": "llama3.2:1b": "prompt": "hi"}'
```

#### Grafana

Exposing Prometheus's built in Grafana GUI:

```bash
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
```

Now open up [Grafana http://localhost:3000/](http://localhost:3000) in the browser.
It will ask you to login. The login information can be found:

```bash
kubectl get secrets -n monitoring | grep grafana
kubectl get secret -n monitoring prometheus-grafana -o jsonpath="{.data.admin-password}" | base64 --decode ; echo
```

This gives you the default login password.
**user**: `admin`
**password**: `<output from get secret>`
You can then change the password in the portal if you want.

#### Prometheus GUI

```bash
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090
```

Now open up [Prometheus http://localhost:9090/](http://localhost:9090/) in the browser.
It is not secured by a password, so **don't do this in production**
