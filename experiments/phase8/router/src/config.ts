export const config = {
    server: {
        host: process.env.ROUTER_HOST ?? "0.0.0.0",
        port: parseInt(process.env.ROUTER_PORT || "11434"),
    },
    ollama: {
        port: parseInt(process.env.OLLAMA_PORT || "11434"),
    },
    discovery: {
        intervalMs: parseInt(process.env.DISCOVERY_INTERVAL_MS || "5000"),
    },
    modelCache: {
        refreshIntervalMs: parseInt(
            process.env.MODEL_CACHE_REFRESH_INTERVAL_MS || "10000",
        ),
        requestTimeoutMs: parseInt(
            process.env.MODEL_CACHE_REQUEST_TIMEOUT_MS || "2000",
        ),
    },
    podPolling: {
        intervalMs: parseInt(process.env.POD_POLLING_INTERVAL_MS || "10000"),
        requestTimeoutMs: parseInt(
            process.env.POD_POLLING_REQUEST_TIMEOUT_MS || "2000",
        ),
    },
    forwarding: {
        responseTimeoutMs: parseInt(
            process.env.FORWARDING_RESPONSE_TIMEOUT_MS || "120000",
        ),
    },
    queue: {
        maxConcurrencyPerPod: parseInt(
            process.env.QUEUE_MAX_CONCURRENCY_PER_POD || "1",
        ),
        maxSizePerTier: parseInt(process.env.QUEUE_MAX_SIZE_PER_TIER || "10"),
        maxWaitMs: parseInt(process.env.QUEUE_MAX_WAIT_MS || "30000"),
    },
};
