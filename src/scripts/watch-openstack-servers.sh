while sleep 10; do
    clear
    openstack server list -f yaml | yq '[.[] | select( .Name | test("ollama-kubernetes") ) | { "name": .Name, "status": .Status }]'
done
