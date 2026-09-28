import * as http from "http";
import TargettingHandler from "./utils/TargettingHandler";
import { PodDiscoveryService } from "./utils/PodDiscovery";
import { QueueItem } from "./models/QueueItem";
import { Pod } from "./models/Pod";
import { config } from "./config";
import { updateQueueMetrics, writeMetrics } from "./utils/metrics";

const targetting = new TargettingHandler();
const discovery = new PodDiscoveryService(targetting.targets);
discovery.startPolling();

updateQueueMetrics();
setInterval(updateQueueMetrics, config.metrics.intervalMs);

async function toJson(request: http.IncomingMessage) {
    return new Promise<{}>((resolve, reject) => {
        let bodyChunks: Buffer[] = [];
        request.on("data", (chunk: Buffer) => bodyChunks.push(chunk));
        request.on("end", () => {
            const bodyBuffer = Buffer.concat(bodyChunks);
            try {
                const bodyJson = JSON.parse(bodyBuffer.toString());
                resolve(bodyJson);
            } catch (error: any) {
                reject(error);
            }
        });
    });
}

const server = http.createServer(
    async (request: http.IncomingMessage, response: http.ServerResponse) => {
        try {
            if (
                request.url === "/api/gateway/status" &&
                request.method === "GET"
            ) {
                response.writeHead(200, { "content-type": "application/json" });
                response.end(
                    JSON.stringify(
                        {
                            timestamp: Date.now(),
                            queues: QueueItem.getQueueSnapshot(),
                            pods: Pod.getStateSnapshot(),
                        },
                        null,
                        2,
                    ),
                );
                return;
            }

            if (
                request.url === "/api/gateway/disable-pod" &&
                request.method === "POST"
            ) {
                const bodyJson: any = await toJson(request);
                const targetPod = Pod.getOrCreate(bodyJson.ip, bodyJson.tier);
                if (targetPod.activeRequests.length == 0) {
                    targetPod.delete();
                    response.writeHead(200);
                    response.end("Success");
                } else {
                    response.writeHead(400);
                    response.end("Pod is already busy with a request");
                }
                return;
            }

            if (request.url === "/metrics" && request.method === "GET") {
                try {
                    await writeMetrics(request, response);
                } catch (error: any) {
                    console.error(`[index] Error serving metrics:`, error);
                    if (!response.headersSent) {
                        response.writeHead(500, {
                            "content-type": "text/plain",
                        });
                    }
                    if (!response.writableEnded) {
                        response.end("Internal server error");
                    }
                } finally {
                    return;
                }
            }

            const contentLength: number = request.headers["content-length"]
                ? parseInt(request.headers["content-length"], 10)
                : NaN;
            const isChunked =
                (request.headers["transfer-encoding"] || "").toLowerCase() ===
                "chunked";
            const hasBody =
                (!isNaN(contentLength) && contentLength > 0) || isChunked;

            if (hasBody) {
                let bodyChunks: Buffer[] = [];
                request.on("data", (chunk: Buffer) => bodyChunks.push(chunk));
                request.on("end", () => {
                    const bodyBuffer = Buffer.concat(bodyChunks);
                    let modelName = null;

                    try {
                        const bodyJson = JSON.parse(bodyBuffer.toString());
                        modelName = bodyJson.model;
                    } catch (error: any) {
                        console.warn(
                            "[index] Failed to parse JSON body:",
                            error.message ?? error.toString(),
                        );
                    }

                    const targetTier = targetting.resolveTargetPod(modelName);
                    new QueueItem(
                        request,
                        response,
                        targetTier.name,
                        bodyBuffer,
                        modelName,
                    ).enqueue();
                });
            } else {
                new QueueItem(
                    request,
                    response,
                    targetting.defaultTarget.name,
                ).enqueue();
            }
        } catch (error: any) {
            const errorId = Math.round(Math.random() * 1000000000);
            console.error(`Error ID: ${errorId} |`, error);
            if (!response.headersSent) {
                response.writeHead(500);
            }
            if (!response.writableEnded) {
                response.end(
                    `Server failed to process request. Error code ${errorId}`,
                );
            }
        }
    },
);

function shutdown() {
    console.log("[index] Shutting down gateway...");
    discovery.stopPolling();
    server.close(() => {
        console.log("[index] Gateway server stopped.");
        process.exit(0);
    });
}

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

server.listen(config.server.port, config.server.host, () => {
    console.log(
        `[index] Gateway listening on http://${config.server.host}:${config.server.port}`,
    );
});
