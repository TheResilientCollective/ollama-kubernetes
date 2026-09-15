import * as http from "http";
import { TargetPod } from "../types/types";

/**
 * Handle forwarding the request from this server to the appropriate target server.
 * Handle streaming and body
 */
export function forwardRequest(
    target: TargetPod,
    request: http.IncomingMessage,
    response: http.ServerResponse,
    bufferedBody: Buffer | null,
): void {
    console.log(
        `[Forwarding] forwarding ${request.url} to ${target.endpoint.hostname}`,
    );
    const headers: http.OutgoingHttpHeaders = { ...request.headers };
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

    const TIMEOUT_MS = 120000;
    proxyRequest.setTimeout(TIMEOUT_MS, () => {
        console.error(
            `[Forwarding] Target "${target.name}" failed to respond within ${TIMEOUT_MS}ms`,
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

    proxyRequest.on("error", (error: any) => {
        console.error(
            `[Forwarding] Failed to proxy to ${target.endpoint.hostname}:`,
            error.message ?? error.toString(),
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
