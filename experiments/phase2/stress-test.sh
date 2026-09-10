#!/bin/bash
set -euo pipefail
# Phase 2: Load test to observe distribution and probe behavior

NAMESPACE="ollama-phase2"
CONCURRENT=5
TOTAL=20
LOCAL_PORT=11432

echo "==> Starting port-forward"
kubectl port-forward -n "$NAMESPACE" svc/ollama "$LOCAL_PORT:11434" &
PF_PID=$!
sleep 2

echo "==> Running hey load test ($TOTAL requests, $CONCURRENT concurrent)"
hey -n "$TOTAL" -c "$CONCURRENT" -m POST \
    -d '{"model": "qwen2.5-coder:3b", "prompt":"Explain why the sky is blue in 1 sentence", "stream":false}' \
    "http://localhost:$LOCAL_PORT/api/generate"

echo -e "\n==> Watching pod logs (distribution)..."
stern -n "$NAMESPACE" -l app=ollama --since 30s --tail 5

kill $PF_PID
