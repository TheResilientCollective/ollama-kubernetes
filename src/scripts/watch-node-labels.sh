while sleep 1; do
    clear
    kubectl get nodes -o json | jq '[.items[] | select(.metadata.name | test("worker") ) | {name: .metadata.name, nvidia: .metadata.labels["nvidia.com/gpu"]}]'
done
