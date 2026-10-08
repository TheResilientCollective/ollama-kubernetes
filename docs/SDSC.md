# Setting up at SDSC

1. [Install Nvidia GPU Drivers](./SDSC GPU Support.md)
2. [Install Kubernetes and connect worker and controller](./SDSC Kubernetes.md)

These steps have already been done for the worker node and saved as the _image_ `ollama-kubernetes-worker k3s and gpu drivers installed` so that new worker nodes can be spawned from this image. These new nodes will automatically connect to the controller[^1] (provided the controller IP doesn't change or is recreated).

3. [Setup Storage Volumes](./SDSC Volumes.md)

## TODO

- [ ] Make the router, scaling, KEDA, prometheus, etc pods run on a designated CPU only VM, not the GPU VMs
- [ ] Scale _nodes_ not _pods_ in response to requests.

---

[^1]: Provided the controller IP doesn't change and the controller isn't destroyed. If the controller is destroyed it will create a new key that the worker nodes need to use to register. You will need to create a new _image_ for the worker nodes to use.
