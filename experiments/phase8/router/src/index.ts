import * as http from "http";
import { forwardRequest } from "./utils/forwarding";
import TargettingHandler from "./utils/TargettingHandler";
import { PodDiscoveryService } from "./utils/PodDiscovery";
import { QueueItem } from "./models/QueueItem";

const PORT = 11434;
const targetting = new TargettingHandler();
const discovery = new PodDiscoveryService(targetting.targets);
discovery.startPolling();

const server = http.createServer(
    (request: http.IncomingMessage, response: http.ServerResponse) => {
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
                    () => {},
                    (error: Error) => {
                        if (!response.headersSent) {
                            response.writeHead(500, {
                                "Content-Type": "application/json",
                            });
                            response.end(
                                JSON.stringify({
                                    error: error.message,
                                }),
                            );
                        }
                    },
                    bodyBuffer,
                    modelName || undefined,
                ).enqueue();
            });
        } else {
            new QueueItem(
                request,
                response,
                targetting.defaultTarget.name,
                () => {},
                (error: Error) => {
                    if (!response.headersSent) {
                        response.writeHead(500, {
                            "content-type": "application/json",
                        });
                        response.end(
                            JSON.stringify({
                                error: error.message,
                            }),
                        );
                    }
                },
            ).enqueue();
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

server.listen(PORT, "0.0.0.0", () => {
    console.log(`[index] Gateway listening on http://0.0.0.0:${PORT}`);
});
