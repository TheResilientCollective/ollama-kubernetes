import * as http from "http";
import { Pod } from "../models/Pod";
import { forwardRequest } from "../utils/forwarding";
import { TargetTier } from "../types/types";
import { config } from "../config";

export class QueueItem {
    private static queues: Map<string, QueueItem[]> = new Map();

    public readonly request: http.IncomingMessage;
    public readonly response: http.ServerResponse;
    public readonly bufferedBody?: Buffer;
    public readonly tier: string;
    public readonly modelName?: string;

    private readonly createdAt: number;

    private isExecuted: boolean = false;
    private enqueuedWaitTimeoutId: NodeJS.Timeout | null = null;
    private get queue(): QueueItem[] | undefined {
        return QueueItem.queues.get(this.tier);
    }

    constructor(
        request: http.IncomingMessage,
        response: http.ServerResponse,
        tier: string,
        bufferedBody?: Buffer,
        modelName?: string,
    ) {
        this.request = request;
        this.response = response;
        this.tier = tier;
        this.bufferedBody = bufferedBody;
        this.modelName = modelName;
        this.createdAt = Date.now();

        // Handle aborted requests
        this.isExecuted = false;
        this.response.on("close", () => {
            if (!this.isExecuted && !this.response.writableEnded) {
                // cancel timeout
                if (this.enqueuedWaitTimeoutId) {
                    clearTimeout(this.enqueuedWaitTimeoutId);
                    this.enqueuedWaitTimeoutId = null;
                }
                // remove from queue
                const queue = this.queue;
                if (queue) {
                    const index = queue.indexOf(this);
                    if (index !== -1) {
                        queue.splice(index, 1);
                        console.log(
                            `[Queue] Removed aborted request for "${this.modelName}" from "${this.tier}" queue before execution.`,
                        );
                    }
                }
            }
        });
    }

    /**
     * Adds this item to the queue,
     * attempts to immediately dispatch
     */
    public enqueue(): void {
        let queue = this.queue;
        if (!queue) {
            queue = [];
            QueueItem.queues.set(this.tier, queue);
        }

        if (queue.length >= config.queue.maxSizePerTier) {
            console.warn(
                `[Queue] Tier "${this.tier}" queue is staurated (queue length ${queue.length}). Rejecting incoming request.`,
            );
            this.response.writeHead(429, {
                "Content-Type": "application/json",
            });
            this.response.end(
                JSON.stringify({
                    error: "Too Many Requests",
                    message:
                        "The cluster is currently experiencing extremely high demand. Please try again later.",
                }),
            );
            return;
        }
        queue.push(this);
        console.log(
            `[Queue] Request enqueued for tier "${this.tier}". Queue length: ${queue.length}`,
        );

        this.enqueuedWaitTimeoutId = setTimeout(
            this.handleQueueTimeout.bind(this),
            config.queue.maxWaitMs,
        );

        QueueItem.dispatch(this.tier);
    }

    /**
     * Handles case where an item has been sitting in the queue for a long time.
     * Sends client an error message and removes from queue
     */
    private handleQueueTimeout() {
        const queue = this.queue;
        if (queue) {
            const index = queue.indexOf(this);
            if (index !== -1) {
                queue.splice(index, 1);
                console.warn(
                    `[Queue] Request for "${this.modelName}" in tier "${this.tier}" timed out waiting in queue.`,
                );
                if (!this.response.headersSent) {
                    this.response.writeHead(503, {
                        "content-type": "application/json",
                    });
                    this.response.end(
                        JSON.stringify({
                            error: "Service Unavailable",
                            message:
                                "The request timed out waiting in the queue due to high demand. Please try again later.",
                        }),
                    );
                }
            }
        }
    }

    /**
     * Attempts to dequeue the next item in all queues.
     * If no pods are available for a queue, that queue is uneffected
     */
    public static dispatchAll(): void {
        for (const [tier] of this.queues) {
            this.dispatch(tier);
        }
    }

    /**
     * Attempts to dequeue the next item in the queue for a given tier.
     * If no pods are available, does nothing.
     */
    public static dispatch(tier: string): void {
        const queue = this.queues.get(tier);
        if (!queue || queue.length === 0) return;
        // Check if there are any available pods
        const pods = Pod.getByTier(tier);
        if (pods.length === 0) {
            console.warn(`[Queue] No pods ready for tier "${tier}" yet.`);
            return;
        }
        const availablePods = pods.filter(
            (pod) =>
                pod.activeRequests.length < config.queue.maxConcurrencyPerPod,
        );
        if (availablePods.length === 0) return;

        // Find the best pod
        const nextQueueItem = queue.shift()!;
        if (!nextQueueItem) return;
        // pod with model already loaded
        let targetPod = availablePods.find((pod) =>
            nextQueueItem.modelName
                ? pod.loadedModels.includes(nextQueueItem.modelName)
                : false,
        );
        // least busy pod
        if (!targetPod) {
            targetPod = availablePods.sort(
                (a, b) => a.activeRequests.length - b.activeRequests.length,
            )[0];
        }

        // Execute
        nextQueueItem.executeOnPod(targetPod);
    }

    /**
     * Sends this queued request to the pod
     */
    private executeOnPod(pod: Pod): void {
        // Make sure request is still active and clear timeouts
        if (
            this.response.destroyed ||
            this.response.writableEnded ||
            this.response.socket?.destroyed
        ) {
            console.log(
                `[Queue] Request for "${this.modelName}" was aborted before execution. Skipping.`,
            );
            QueueItem.dispatch(this.tier);
            return;
        }
        this.isExecuted = true;
        if (this.enqueuedWaitTimeoutId) {
            clearTimeout(this.enqueuedWaitTimeoutId);
            this.enqueuedWaitTimeoutId = null;
        }

        // Add item to pod's active requests
        pod.activeRequests.push(this);
        const queueDuration = Date.now() - this.createdAt;
        console.log(
            `[Queue] Request for model: "${this.modelName}" in tier: "${this.tier}" took ${queueDuration}ms to dequeue.`,
        );

        // Execute
        const targetTier: TargetTier = {
            name: pod.ip,
            endpoint: new URL(
                this.request.url || "/",
                `http://${pod.ip}:11434`,
            ),
            size: 0,
            headlessDns: "",
        };
        forwardRequest(
            targetTier,
            this.request,
            this.response,
            this.bufferedBody,
        ).finally(
            (() => {
                pod.activeRequests = pod.activeRequests.filter(
                    (item) => item !== this,
                );
                QueueItem.dispatch(this.tier);
            }).bind(this),
        );
    }

    public static getQueueSnapshot() {
        const snapshot: Record<string, any> = {};
        for (const [tier, queue] of this.queues) {
            snapshot[tier] = {
                length: queue.length,
                items: queue.map((item) => ({
                    modelName: item.modelName,
                    queuedDurationMs: Date.now() - item.createdAt,
                })),
            };
        }
        return snapshot;
    }
}
