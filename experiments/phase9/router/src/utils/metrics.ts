import { register, Gauge, Counter, Histogram } from "prom-client";
import { QueueSnapshot } from "../types/types";
import { config } from "../config";
import { QueueItem } from "../models/QueueItem";
import * as http from "http";

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

/**
 * Updates the local prometheus metrics.
 * Does not publish to prometheus itself.
 */
export function updateQueueMetrics() {
    const queueSnapshot: QueueSnapshot = QueueItem.getQueueSnapshot();
    const averageQueueTimes = QueueItem.consumeAverageQueueTimes();
    config.tiers.forEach((tier: string) => {
        if (queueSnapshot[tier]) {
            queueLengthGauge.set({ tier }, queueSnapshot[tier].length);
        }
        if (averageQueueTimes.get(tier)) {
            const queueTimes = averageQueueTimes.get(tier)!;
            const average = queueTimes.sum / queueTimes.count;
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
