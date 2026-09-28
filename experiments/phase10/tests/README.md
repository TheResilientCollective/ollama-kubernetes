# Testing

## Running things locally for testing

### Run **scaling-controller**

```bash
# Assuming namespace is "ollama"
# Make sure ollama-router is exposed
kubectl port-forward -n ollama svc/ollama-router 11439:11434

cd scaling-controller/
source .venv/bin/activate
uv sync
DEBUG=true ROUTER_ENDPOINT="http://localhost:11439" NAMESPACE="ollama" python src/main.py
```

### Run **router**

Requires a bunch of extra environment variables and won't run cleanly without them.
`TARGET_<SIZE>_ENDPOINT`, `TARGET_<SIZE>_SIZE`, and `TARGET_<SIZE>_HEADLESS_DNS` where `<SIZE>` is `SMALL`, `MEDIUM`, and `LARGE`. You will also have to make sure all ports are correctly forwarding. I'm not sure that is realistic to run this server outside of the kubernetes deployment.

```bash
cd router/
npm install
npm run build
npm run start
```
