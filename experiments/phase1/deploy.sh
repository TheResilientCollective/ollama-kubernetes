#!/bin/bash
set -euo pipefail

# Phase 1: Static Ollama Deployment
# Purpose: Deploy Ollama with llama3 model to Kubernetes
# Prerequisites: Orbstack Kubernetes running, kubectl configured

NAMESPACE="ollama-phase1"
DEPLOYMENT_NAME="ollama"
MODEL="qwen2.5-coder:3b"

setup_namespace() {
    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
}

deploy_manifests() {
    kubectl apply -f deployment.yaml -n "$NAMESPACE"
    kubectl apply -f service.yaml -n "$NAMESPACE"
}

wait_for_ready() {
    kubectl wait --for=condition=ready pod -l app=ollama -n "$NAMESPACE" --timeout=300s
}

pull_model() {
    # Wait for Ollama to start, then pull model
    kubectl exec -n "$NAMESPACE" deployment/ollama -- ollama pull "$MODEL"
}

main() {
    echo "==> Phase 1: Deploying Ollama with $MODEL"
    setup_namespace
    deploy_manifests
    wait_for_ready
    pull_model
    echo "==> Deployment successful!"
}

if [[ ${BASH_SOURCE[0]} == "${0}" ]]; then
    main "$@"
fi
