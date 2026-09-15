import * as http from "http";
import { forwardRequest } from "./utils/forwarding";
import TargettingHandler from "./utils/TargettingHandler";

const PORT = 11434;
const targetting = new TargettingHandler();

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

                const target = targetting.resolveTargetPod(modelName);
                forwardRequest(target, request, response, bodyBuffer);
            });
        } else {
            forwardRequest(targetting.defaultTarget, request, response, null);
        }
    },
);

server.listen(PORT, "0.0.0.0", () => {
    console.log(`[index] Gateway listening on http://0.0.0.0:${PORT}`);
});
