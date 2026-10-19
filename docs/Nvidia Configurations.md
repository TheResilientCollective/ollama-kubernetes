# Nvidia Configurations

The following is a few useful pointers when running this on nodes that have nvidia GPUs.

Prerequisites:

- If running in a datacenter, you will have to determine the necessary drivers to get the GPU to register with the OS as a usable GPU (e.g. [SDSC GPU Support](./SDSC GPU Support.md).
- installed NVIDIA drivers and the nvidia-container-toolkit
- configured the nvidia-container-runtime as the default low-level runtime to use

## Labelling your nodes

Each node will need to be labeled as having a GPU so Kubernetes knows it has the necessary hardware for the small/medium/large pods.

```bash
kubectl label node ollama-kubernetes-worker-small-1 nvidia.com/gpu=true
```

replacing `ollama-kubernetes-worker-small-1` with the name of your node/s.

## Installing the Nvidia Device Plugin

This lets the node advertise what kind of GPU it has to the controller. The following should be done on the GPU nodes (not the controller)

### Make sure Nvidia Container Toolkit is installed

This will be a bit finnicky and depend on your exact infrastructure, but the following worked for me on ubuntu 24.04:
On the worker node:

```bash
# Install NVIDIA container runtime (k3s will auto-detect it)
sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg2
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-runtime

# Restart k3s to trigger auto-detection
sudo systemctl restart k3s-agent

# Verify NVIDIA runtime was detected (should show nvidia entries)
sudo grep nvidia /var/lib/rancher/k3s/agent/etc/containerd/config.toml
```

### Patch K3s

On the controller node:

```bash
# Install device plugin
kubectl create -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.17.1/deployments/static/nvidia-device-plugin.yml

# Patch it for k3s (using the script file I created)
bash /Users/tlsharkey/.opencode/plan/patch-nvidia-device-plugin.sh

# Check GPU capacity
kubectl describe nodes | grep -A10 "Capacity"
```

### Add Nvidia Runtime Spec

On controller node:

```bash
kubectl patch deployment -n ollama ollama-small --type merge -p '{"spec":{"template":{"spec":{"runtimeClassName":"nvidia"}}}}'

kubectl rollout restart deployment -n ollama ollama-small
kubectl rollout status deployment -n ollama ollama-small
```
