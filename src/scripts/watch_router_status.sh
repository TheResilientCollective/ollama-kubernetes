if [[ -z $TIER ]]; then
    echo "Error: TIER is required" >&2
    echo 'Set TIER="medium" before executing' >&2
    exit 1
fi

while sleep 1; do
    clear
    curl http://localhost:11439/api/gateway/status | jq \
        --arg tier "$TIER" '
        {
            queue: (.queues[$tier].length // 0),
            pods: (.pods[$tier] | length // 0),
            running: [(.pods[$tier] // [])[] | .activeRequests]
        }'
done
