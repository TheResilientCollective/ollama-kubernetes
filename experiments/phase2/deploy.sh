#!/bin/bash
set -euo pipefail

# Phase 2: Deploy Ollama with resources and probes
# Prerequisites: Orbstack running, ollama-phase2 namespace exists

NAMESPACE="ollama-phase2"
DEPLOYMENT_NAME="ollama"
MODEL="qwen2.5-coder:3b"

kubectl apply -f deployment.yaml -n "$NAMESPACE"
kubectl apply -f service.yaml -n "$NAMESPACE"

kubectl rollout status deployment/"$DEPLOYMENT_NAME" -n "$NAMESPACE" --timeout=300s
