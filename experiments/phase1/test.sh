#!/bin/bash
set -euo pipefail

# Phase 1: Test Ollama Deployment
# Purpose: Validate deployment works end-to-end

NAMESPACE="ollama-phase1"
LOCAL_PORT=11434

port_forward() {
    kubectl port-forward -n "$NAMESPACE" svc/ollama "$LOCAL_PORT:11434" &
    PF_PID=$!
    sleep 3
    trap "kill $PF_PID 2>/dev/null" EXIT
}

test_generate() {
    echo "==> Testing Ollama API..."
    curl -s -X POST http://localhost:$LOCAL_PORT/api/generate \
        -d '{"model": "qwen2.5-coder:3b", "prompt": "Say hello in one sentence", "stream": false}' |
        jq -r '.response'
}

test_model_list() {
    echo "==> Listing available models..."
    curl -s http://localhost:$LOCAL_PORT/api/tags | jq .
}

main() {
    echo "==> Phase 1: Testing Ollama deployment"
    port_forward
    test_model_list
    test_generate
    echo "==> All tests passed!"
}

if [[ ${BASH_SOURCE[0]} == "${0}" ]]; then
    main "$@"
fi
