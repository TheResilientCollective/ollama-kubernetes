# Phase 9

## KEDA CRD dependency

Unfortunately KEDA must be installed to the system in order for this to work. Just adding as a dependency isn't enough, because the Custom Resource Definitions that KEDA is looking for in the yaml files (`ScaledObject`) aren't valid until after KEDA has extended Kubernetes. This means it can't be added as a simple dependency that gets installed in the deployment process.

Additionally, best practice is separating out prometheus, so this also needs to be installed independently in the global namespace.

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
kubectl port-forward -n ollama-phase9 deployment/ollama-router 11434:11434
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
