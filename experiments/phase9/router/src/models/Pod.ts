import * as http from "http";
import { config } from "../config";
import { PodStateSnapshot } from "../types/types";

export class Pod {
    private static pods: Map<string, Pod> = new Map();

    public readonly ip: string;
    public readonly tier: string;
    public activeRequests: any[] = []; // FIXME: move to a queue item?
    public loadedModels: string[] = [];
    public lastPolled: number = 0;
    private pollingIntervalId: NodeJS.Timeout | null = null;
    public get isPolling(): boolean {
        return this.pollingIntervalId !== null;
    }

    private constructor(ip: string, tier: string) {
        this.ip = ip;
        this.tier = tier;
        Pod.pods.set(ip, this);
        this.startPolling();
    }

    /**
     * Gets the pod with a given ip and tier
     * If the pod doesn't exist, will create the object.
     * Does not actually spawn the kubernetes pod
     */
    public static getOrCreate(ip: string, tier: string): Pod {
        return this.pods.get(ip) || new Pod(ip, tier);
    }

    /**
     * Gets all pods in a tier
     */
    public static getByTier(tier: string): Pod[] {
        return Array.from(this.pods.values()).filter((p) => p.tier === tier);
    }

    /**
     * Removes all pods except a subset
     * @param (string[]) ipsToKeep: the list of ip addresses to keep (to not prune)
     */
    public static pruneAllExcept(ipsToKeep: string[]): void {
        for (const [ip] of this.pods) {
            if (ipsToKeep.includes(ip)) continue; // don't prune
            this.pods.get(ip)?.delete();
            console.log(`[PodRegistry] Pruned ip ${ip}`);
        }
    }

    /**
     * Deletes all pods
     */
    public static clear(): void {
        this.pods.clear();
    }

    /**
     * Gets a snapshot of pods, ips, and requests.
     * Useful for observability
     */
    public static getStateSnapshot(): PodStateSnapshot {
        const snapshot: Record<string, any[]> = {};
        for (const [ip, pod] of this.pods) {
            if (!snapshot[pod.tier]) {
                snapshot[pod.tier] = [];
            }
            snapshot[pod.tier].push({
                ip: pod.ip,
                activeRequests: pod.activeRequests.length,
                loadedModels: pod.loadedModels,
                lastPolledMsAgo: Date.now() - pod.lastPolled,
            });
        }
        return snapshot;
    }

    /**
     * Removes a pod from tracked pods and stops regular polling
     */
    public delete(): void {
        this.stopPolling();
        Pod.pods.delete(this.ip);
    }

    /**
     * Begins regular check of which models are loaded on this pod
     */
    public startPolling(): void {
        if (this.isPolling) this.stopPolling();

        this.pollingIntervalId = setInterval(
            () => this.getLoadedModels(),
            config.podPolling.intervalMs,
        );
    }

    /**
     * Stops regular check of which models are loaded on this pod
     */
    public stopPolling(): void {
        if (this.pollingIntervalId) {
            clearInterval(this.pollingIntervalId);
            this.pollingIntervalId = null;
        }
    }

    /**
     * Gets the models currently loaded in memory
     */
    private async getLoadedModels(): Promise<void> {
        return new Promise<void>((resolve) => {
            const url = `http://${this.ip}:${config.ollama.port}/api/ps`;
            const request = http.get(url, (response) => {
                let data = "";
                response.on("data", (chunk: string | Buffer) => {
                    data += chunk;
                });
                response.on("end", () => {
                    if (response.statusCode === 200) {
                        try {
                            const parsed = JSON.parse(data);
                            const models: string[] = (parsed.models || []).map(
                                (m: any) => m.name,
                            );

                            this.loadedModels = models;
                            this.lastPolled = Date.now();
                        } catch (error: any) {
                            console.error(
                                `[Pod] Failed to parse /api/ps from ${this.ip}:`,
                                error.message,
                            );
                        }
                    } else {
                        this.loadedModels = [];
                    }
                    resolve();
                });
            });

            request.setTimeout(config.podPolling.requestTimeoutMs, () => {
                request.destroy();
            });

            request.on("error", (error: any) => {
                // TODO: potentially spin down this pod and remove it from available pods
                this.loadedModels = [];
                resolve();
            });
        });
    }
}
