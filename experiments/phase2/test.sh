#!/bin/bash
set -euo pipefail

# Phase 1: Test Ollama Deployment
# Purpose: Validate deployment works end-to-end

NAMESPACE="ollama-phase2"
LOCAL_PORT=11432

port_forward() {
    kubectl port-forward -n "$NAMESPACE" svc/ollama "$LOCAL_PORT:11434" &
    PF_PID=$!
    sleep 3
    trap "kill $PF_PID 2>/dev/null" EXIT
}

test_status() {
    echo "==> 1. Pod status (Running vs Ready)"
    kubectl get pods -n "$NAMESPACE" -l app=ollama -o wide
    echo -e "\n==> 2. Probe configuration"
    kubectl describe deployment ollama -n "$NAMESPACE" | grep -A 15 "Readiness:\|Liveness:"
}

test_resources() {
    echo -e "\n==> 3. Resource requests/limits"
    kubectl describe deployment ollama -n "$NAMESPACE" | grep -A 10 "Requests:\|Limits:"
}

test_generate() {
    echo "==> 5. Testing generation"
    curl -s -X POST http://localhost:$LOCAL_PORT/api/generate \
        -d '{"model": "qwen2.5-coder:3b", "prompt": "Say hello in one sentence", "stream": false}' |
        jq -r '.response'
}

test_model_list() {
    echo "==> Listing available models..."
    curl -s http://localhost:$LOCAL_PORT/api/tags | jq .
}

test_metrics_server() {
    echo -e "\n==> 6. Resource usage (metrics-server)"
    kubectl top pods -n "$NAMESPACE" --containers || echo "metrics-server not ready yet"
}

test_events() {
    echo -e "\n==> 7. Events (probe failures, scheduling)"
    kubectl get events -n "$NAMESPACE" --sort-by='.lastTimestamp' | tail -20
}

main() {
    echo "==> Phase 2: Testing Ollama deployment"
    port_forward
    test_status
    test_resources
    test_model_list
    test_generate
    test_metrics_server
    test_events
    echo "==> All tests passed!"
}

if [[ ${BASH_SOURCE[0]} == "${0}" ]]; then
    main "$@"
fi
