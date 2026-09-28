import * as http from "http";
import { TargetTier } from "../types/types";
import { config } from "../config";

/**
 * Handle forwarding the request from this server to the appropriate target server.
 * Handle streaming and body
 */
export async function forwardRequest(
    target: TargetTier,
    request: http.IncomingMessage,
    response: http.ServerResponse,
    bufferedBody?: Buffer,
): Promise<void> {
    return new Promise<void>((resolve) => {
        console.log(
            `[Forwarding] forwarding ${request.url} to ${target.endpoint.hostname}`,
        );
        let isResponseStarted = false;
        let isFinished = false;

        // Make the request
        const headers: http.OutgoingHttpHeaders = { ...request.headers };
        headers["host"] = target.endpoint.host;
        if (bufferedBody) {
            headers["content-length"] = bufferedBody.length;
            delete headers["transfer-encoding"];
        }
        const proxyRequest = http.request(
            {
                hostname: target.endpoint.hostname,
                port: target.endpoint.port,
                path: request.url,
                method: request.method,
                headers: headers,
            },
            (proxyResponse: http.IncomingMessage) => {
                isResponseStarted = true;
                if (!response.headersSent)
                    response.writeHead(
                        proxyResponse.statusCode || 200,
                        proxyResponse.headers,
                    );
                proxyResponse.pipe(response);
            },
        );

        function handleProxyError(error: any) {
            console.error(
                `[Forwarding] Failed to proxy to ${target.endpoint.hostname}:`,
                error.message ?? error.toString(),
            );

            if (!isResponseStarted) {
                if (!response.headersSent) {
                    response.writeHead(502, {
                        "content-type": "application/json",
                    });
                }
                response.end(
                    JSON.stringify({
                        error: "Bad Gateway",
                        message: `Target pod "${target.name}" is currently unavailable (${error.message})`,
                    }),
                );
            } else {
                response.end();
            }
            cleanupAndResolve();
        }

        function handleProxyTimeout() {
            console.error(
                `[Forwarding] Target "${target.name}" failed to respond within ${config.forwarding.responseTimeoutMs}ms`,
            );
            proxyRequest.destroy();

            if (!isResponseStarted) {
                if (!response.headersSent)
                    response.writeHead(504, {
                        "Content-Type": "application/json",
                    });
                response.end(
                    JSON.stringify({
                        error: "Gateway Timeout",
                        message: `The sizing pod "${target.name}" took too long to begin responding. This can happen during cold starts or model loading deadlocks.`,
                    }),
                );
            } else {
                if (!response.writableEnded) {
                    response.end();
                }
            }
            cleanupAndResolve();
        }

        function handleClientClose() {
            if (!isFinished) {
                if (!response.writableEnded) {
                    console.log(
                        `[Forwarding] Client connection aborted. Destroying backend proxy request to ${target.endpoint.hostname}`,
                    );
                    proxyRequest.destroy();
                }
                cleanupAndResolve();
            }
        }

        function cleanupAndResolve() {
            if (isFinished) return;
            isFinished = true;
            resolve();
        }

        proxyRequest.setTimeout(
            config.forwarding.responseTimeoutMs,
            handleProxyTimeout,
        );
        proxyRequest.on("error", handleProxyError);

        response.on("finish", cleanupAndResolve);
        response.on("close", handleClientClose);

        if (bufferedBody) {
            proxyRequest.write(bufferedBody);
        }
        proxyRequest.end();
    });
}
