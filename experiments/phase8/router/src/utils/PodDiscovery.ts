import * as dns from "dns/promises";
import { Pod } from "../models/Pod";
import { TargetTier } from "../types/types";
import { QueueItem } from "../models/QueueItem";
import { config } from "../config";

export class PodDiscoveryService {
    private targets: TargetTier[];
    private intervalId: NodeJS.Timeout | null = null;

    constructor(targets: TargetTier[]) {
        this.targets = targets;
    }

    /**
     * Periodically queries headless DNS for all tiers
     */
    public startPolling(): void {
        this.discoverAll();
        this.intervalId = setInterval(
            this.discoverAll.bind(this),
            config.discovery.intervalMs,
        );
    }

    public stopPolling(): void {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }
    }

    private async discoverAll(): Promise<void> {
        const activeIps = new Set<string>();

        for (const target of this.targets) {
            if (!target.headlessDns) continue;

            try {
                const ips = await dns.resolve4(target.headlessDns);

                for (const ip of ips) {
                    activeIps.add(ip);
                    Pod.getOrCreate(ip, target.name);
                }
            } catch (error: any) {
                if (error.code !== "ENODATA" && error.code !== "ENOTFOUND") {
                    console.error(
                        `[PodDiscovery] Error resolving DNS for tier "${target.name}":`,
                        error.message,
                    );
                }
            }
        }

        Pod.pruneAllExcept(Array.from(activeIps));
        QueueItem.dispatchAll(); // In case of any new pods, try executing queue
    }
}
