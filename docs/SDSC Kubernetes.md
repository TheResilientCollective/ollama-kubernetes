# Setting up Kubernetes on SDSC

## Controller Node

### Install k3s

```bash
PUBLIC_IP=$(curl ifconfig.me)
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.30.6+k3s1 sh -s - server --cluster-init --disable traefik --tls-san $PUBLIC_IP --node-taint node-role.kubernetes.io/control-plane:NoSchedule
```

Now we need the token the workers will use to register themselves with the controller

```bash
sudo cat /var/lib/rancher/k3s/server/node-token
```

The output of is needed for the Worker Node setup below.

```bash
sudo k3s kubectl get nodes
```

There should be empty.

Add alias for `kubectl`

```bash
alias kubectl="k3s kubectl"
```

## Worker Node

### 1. Install k3s and register with controller

```bash
CONTROLLER_INTERNAL_IP="192.168.0.x"
K3S_TOKEN="<get from the controller>"

curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.30.6+k3s1 K3S_URL="https://$CONTROLLER_INTERNAL_IP:6443" K3S_TOKEN=$K3S_TOKEN sh -s - agent 2>&1 | tee k3sInstallation.log & disown
```

Note: do not try to rerun this if it fails. Destroy the VM and start over.

This took a long time to run the first time and got hung up, hence the piping logs and disowning. It keeps hanging after the log `[INFO]  systemd: Starting k3s-agent`
While this is running, or when it's finished, check the **controller node** for the worker node appearing: `sudo kubectl get nodes`

Check to make sure k3s has finished initializing (in a different ssh session)

```bash
sudo systemctl show k3s-agent -p ActiveState -p SubState
sudo journalctl -u k3s-agent --no-pager --lines=30 | tail -30
```
