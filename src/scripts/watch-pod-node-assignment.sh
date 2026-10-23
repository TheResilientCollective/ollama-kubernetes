TIER="${TIER:-}"

while sleep 1; do
    clear
    kubectl get pods -n ollama -o json | jq --arg tier "$TIER" '[
        .items[] | select(.metadata.name | test("ollama-" + $tier)) | { 
            pod: .metadata.name, 
            podReady: (.status.conditions[]? | select(.type == "Ready") | .status),
            node: .spec.nodeName
        }
    ]'
done
