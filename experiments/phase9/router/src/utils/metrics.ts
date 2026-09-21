import { register, Gauge, Counter, Histogram } from "prom-client";
import { PodSnapshot, PodStateSnapshot, QueueSnapshot } from "../types/types";
import { config } from "../config";
import { QueueItem } from "../models/QueueItem";
import * as http from "http";
import { Pod } from "../models/Pod";

const queueLengthGauge = new Gauge({
    name: "ollama_gateway_queue_length",
    help: "For the various pod sizes (small/medium/large), each has its own queue. This is the current length of that queue, with pod tier labels",
    labelNames: ["tier"],
});

const waitTimeHistogram = new Histogram({
    name: "ollama_gateway_wait_time_seconds",
    help: "The time requests spend waiting in the queue",
    labelNames: ["tier"],
    buckets: [0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300],
});

const totalQueries = new Gauge({
    name: "ollama_gateway_all_pending_queries",
    help: "All of the requests that are currently being handled by a pod and all of the queued requests. sum(activeRequests, queuedRequests)",
    labelNames: ["tier"],
});

/**
 * Updates the local prometheus metrics.
 * Does not publish to prometheus itself.
 */
export function updateQueueMetrics() {
    const queueSnapshot: QueueSnapshot = QueueItem.getQueueSnapshot();
    const podSnapshot: PodStateSnapshot = Pod.getStateSnapshot();
    const averageQueueTimes = QueueItem.consumeAverageQueueTimes();
    config.tiers.forEach((tier: string) => {
        if (queueSnapshot[tier]) {
            const queuedRequestsInTier = queueSnapshot[tier].length;
            queueLengthGauge.set({ tier }, queuedRequestsInTier);

            const activePodsInTier: PodSnapshot[] = podSnapshot[tier];
            const activeRequestsInTier: number = activePodsInTier
                .map((pod) => pod.activeRequests)
                .reduce((sum, accumulator) => sum + accumulator, 0);
            totalQueries.set(
                { tier },
                activeRequestsInTier + queuedRequestsInTier,
            );
        }
        if (averageQueueTimes.get(tier)) {
            const queueTimes = averageQueueTimes.get(tier)!;
            const average: number = queueTimes.sum / queueTimes.count;
            waitTimeHistogram.observe({ tier }, average);
        }
    });
}

/**
 * Writes prometheus metrics out to an endpoing
 */
export async function writeMetrics(
    request: http.IncomingMessage,
    response: http.ServerResponse,
) {
    const metrics = await register.metrics();
    response.writeHead(200, {
        "content-type": register.contentType,
    });
    response.end(metrics);
    console.log(`[index] /metrics served`);
}
