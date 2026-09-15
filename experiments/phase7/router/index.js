const http = require("http");

const PORT = 11434;

/**
 * Parses a string like "3Gi" into number of bytes
 */
function parseK8sSize(sizeStr) {
    if (!sizeStr) return 0;
    const match = sizeStr.trim().match(/^(\d+(?:\.\d+)?)\s*([a-zA-Z]+)?$/);
    if (!match || match.length !== 3) return 0;
    const value = parseFloat(match[1]);
    const unit = match[2].toLowerCase();
    switch (unit) {
        case "ti":
        case "tib":
            return value * 1024 * 1024 * 1024 * 1024;
        case "t":
        case "tb":
            return value * 1000 * 1000 * 1000 * 1000;
        case "gi":
        case "gib":
            return value * 1024 * 1024 * 1024;
        case "g":
        case "gb":
            return value * 1000 * 1000 * 1000;
        case "mi":
        case "mib":
            return value * 1024 * 1024;
        case "m":
        case "mb":
            return value * 1000 * 1000;
        case "ki":
        case "kib":
            return value * 1024;
        case "k":
        case "kb":
            return value * 1000;
        default:
            return value;
    }
}

// Parse environment variables to get the tiers
const targets = Object.keys(process.env)
    .filter((key) => key.startsWith("TARGET_") && key.endsWith("_SIZE"))
    .map((key) => key.replace("TARGET_", "").replace("_SIZE", ""))
    .map((size) => ({
        name: size.toLowerCase(),
        endpoint: new URL(process.env[`TARGET_${size}_ENDPOINT`]),
        size: parseK8sSize(process.env[`TARGET_${size}_SIZE`]),
    }));
targets.sort((a, b) => a.size - b.size);
const defaultTarget = targets[0];
console.log("Dynamic Router initialized with targets", targets);

//// Keeping track of available models ////

let modelSizeCache = {};
function refreshModelSizes() {
    let success = false;

    function tryEndpoint(index) {
        if (index >= targets.length) {
            console.error(
                `tryEndpoint called with index ${index}, which is out of bounds of available targets (${targets.length} targets available)`,
            );
            return;
        }

        const target = targets[index];
        console.log(`Fetching /api/tags from ${target.endpoint.origin}`);

        const request = http.get(
            target.endpoint.origin + "/api/tags",
            (response) => {
                let data = "";
                response.on("data", (chunk) => {
                    data += chunk;
                });
                response.on("end", () => {
                    try {
                        const parsed = JSON.parse(data);
                        if (parsed.models) {
                            const newCache = {};
                            parsed.models.forEach((model) => {
                                newCache[model.name] = model.size;
                            });
                            modelSizeCache = newCache;
                            success = true;
                            console.log(
                                "[Router] Cache refreshed successfully:",
                                Object.keys(modelSizeCache),
                            );
                        }
                    } catch (e) {
                        console.error(
                            `Failed to parse /api/tags from ${target.endpoint.origin}`,
                            e,
                        );
                    }
                    if (!success) tryEndpoint(index + 1);
                });
            },
        );
        request.on("error", () => {
            tryEndpoint(index + 1);
        });
        request.setTimeout(2000, () => {
            request.destroy();
            tryEndpoint(index + 1);
        });
    }

    tryEndpoint(0);
}

refreshModelSizes();
setInterval(refreshModelSizes, 10000);

/**
 * Determines which pod should be used for a given model
 * based on the size of that model and the size of the pod
 */
function resolveTargetPod(modelName) {
    if (!modelName) return defaultTarget;

    // Get size of the requested model
    const sizeBytes = modelSizeCache[modelName];
    if (!sizeBytes) {
        console.log(`[Router] Model "${modelName}" not found in cache.`);
        return defaultTarget;
    }

    // Find a pod with enough memory for the model
    for (const target of targets) {
        if (sizeBytes < target.size) {
            console.log(
                `[Router] Model "${modelName}" (${(sizeBytes / 1024 / 1024 / 1024).toFixed(2)} GB) -> Tier: ${target.name}`,
            );
            return target;
        }
    }

    // Fallback to largest pod
    const largest = targets[targets.length - 1];
    console.log(
        `[Router] Model "${modelName}" exceeds all tier sizes. Routing to largest pod: ${largest.endpoint.origin}`,
    );
    return largest;
}

//// Run Server ////
/**
 * Handle forwarding the request from this server to the appropriate target server.
 * Handle streaming and body
 */
function forwardRequest(target, request, response, bufferedBody) {
    console.log(
        `[ForwardRequest] forwarding ${request.url} to ${target.endpoint.hostname}`,
    );
    const headers = { ...request.headers };
    headers["host"] = target.endpoint.host;
    if (bufferedBody) {
        headers["content-length"] = bufferedBody.length;
        delete headers["transfer-encoding"];
    }

    let isResponseStarted = false;

    const proxyRequest = http.request(
        {
            hostname: target.endpoint.hostname,
            port: target.endpoint.port,
            path: request.url,
            method: request.method,
            headers: request.headers,
        },
        (proxyResponse) => {
            isResponseStarted = true;
            if (!response.headersSent)
                response.writeHead(
                    proxyResponse.statusCode,
                    proxyResponse.headers,
                );
            proxyResponse.pipe(response);
        },
    );

    const TIMEOUT_MS = 120000;
    proxyRequest.setTimeout(TIMEOUT_MS, () => {
        console.error(
            `[Router Timeout] Target "${target.name}" failed to respond within ${TIMEOUT_MS}ms`,
        );
        proxyRequest.destroy();

        if (!isResponseStarted) {
            if (!response.headersSent)
                response.writeHead(504, { "Content-Type": "application/json" });
            response.end(
                JSON.stringify({
                    error: "Gateway Timeout",
                    message: `The sizing pod "${target.name}" took too long to begin responding. This can happen during cold starts or model loading deadlocks.`,
                }),
            );
        }
    });

    proxyRequest.on("error", (error) => {
        console.error(
            `[Router Error] Failed to proxy to ${target.endpoint.hostname}:`,
            error.message,
        );

        if (!isResponseStarted) {
            response.end(
                JSON.stringify({
                    error: `Bad Gateway: Target pod "${target.name}" is currently unavailable (${error.message})`,
                }),
            );
        } else {
            response.end();
        }
    });

    if (bufferedBody) {
        proxyRequest.write(bufferedBody);
    }
    proxyRequest.end();
}

const server = http.createServer((request, response) => {
    const contentLength = parseInt(request.headers["content-length"], 10);
    const isChunked =
        (request.headers["transfer-encoding"] || "").toLowerCase() ===
        "chunked";
    const hasBody = (!isNaN(contentLength) && contentLength > 0) || isChunked;

    if (hasBody) {
        let bodyChunks = [];
        request.on("data", (chunk) => bodyChunks.push(chunk));
        request.on("end", () => {
            const bodyBuffer = Buffer.concat(bodyChunks);
            let modelName = null;

            try {
                const bodyJson = JSON.parse(bodyBuffer.toString());
                modelName = bodyJson.model;
            } catch (error) {
                console.warn(
                    "[Router] Failed to parse JSON body:",
                    error.message,
                );
            }

            const target = resolveTargetPod(modelName);
            forwardRequest(target, request, response, bodyBuffer);
        });
    } else {
        forwardRequest(defaultTarget, request, response, null);
    }
});

server.listen(PORT, "0.0.0.0", () => {
    console.log(`[Router] Gateway listening on http://0.0.0.0:${PORT}`);
});
