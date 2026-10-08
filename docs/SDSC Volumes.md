# Connecting Volumes

The _volume_ id for the Cinder volume in OpenStack is `da8130ee-f450-4fc4-bb07-cd7fa625fb8a`

You'll probably have to do this for each node:

```bash
openstack server add volume ollama-kubernetes-worker-small-1 da8130ee-f450-4fc4-bb07-cd7fa625fb8a
```

And then on the node itself:

```bash
DEVICE=$(lsblk -pd -o NAME,TYPE | grep disk | grep -v vda | tail -1 | awk '{print $1}')
sudo mkfs.ext4 $DEVICE
sudo mkdir -p /var/lib/rancher/k3s/storage/ollama-models
sudo echo "$DEVICE /var/lib/rancher/k3s/storage/ollama-models ext4 defaults,nofail 0 2" >> /etc/fstab # This gave me an error so I had to edit fstab manually
sudo systemctl daemon-reload
sudo mount -a
```

/var/lib/rancher/k3s/storage/ollama-models is now only viewable via sudo. To make sure the path is picked up:

On controller:

```bash
kubectl drain ollama-kubernetes-worker-small-1 --ignore-daemonsets --delete-emptydir-data
```

On worker:

```bash
sudo systemctl restart k3s-agent
```

On controller:

```bash
kubectl uncordon ollama-kubernetes-worker-small-1
```
