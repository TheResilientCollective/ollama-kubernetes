while sleep 1; do
    clear
    kubectl get pods -n ollama -o json | jq '[
    .items[] | 
        select( .metadata.name | test("ollama-small") ) | 
        { 
            pod: .metadata.name, 
            podReady: (
                .status.conditions[] | 
                    select(.type | test("Ready")) | .status 
            ),
            node: .spec.nodeName
        }
    ]'
done
