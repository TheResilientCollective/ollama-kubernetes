import { TargetTier } from "../types/types";
import { parseK8sSize } from "./utils";
import * as http from "http";

export default class TargettingHandler {
    targets: TargetTier[];
    defaultTarget: TargetTier;
    modelSizeCache: Record<string, number> = {};

    constructor() {
        // Parse environment variables to get the tiers
        this.targets = Object.keys(process.env)
            .filter((key) => key.startsWith("TARGET_") && key.endsWith("_SIZE"))
            .map((key) => key.replace("TARGET_", "").replace("_SIZE", ""))
            .map((size) => {
                const endpointVariable: string =
                    process.env[`TARGET_${size}_ENDPOINT`] || "";
                const sizeVariable: string =
                    process.env[`TARGET_${size}_SIZE`] || "";
                const headlessDnsVariable: string =
                    process.env[`TARGET_${size}_HEADLESS_DNS`] || "";
                return {
                    name: size.toLowerCase(),
                    endpoint: new URL(endpointVariable),
                    size: parseK8sSize(sizeVariable),
                    headlessDns: headlessDnsVariable,
                } as TargetTier;
            });
        this.targets.sort((a, b) => a.size - b.size);
        if (this.targets.length === 0) {
            throw new Error(
                "[TargettingHandler] No target pods configured. Ensure TARGET_<SIZE>_ENDPOINT and TARGET_<SIZE>_SIZE are set.",
            );
        }

        this.defaultTarget = this.targets[0];
        console.log(
            "[TargettingHandler] Dynamic Router initialized with targets",
            this.targets,
        );

        this.updateModelCache();
        setInterval(this.updateModelCache.bind(this), 10000);
    }

    /**
     * Determines which pod should be used for a given model
     * based on the size of that model and the size of the pod
     * @param (string) modelName: the name of the LLM model
     * @returns (TargetPod) the smallest pod that can run the model
     */
    resolveTargetPod(modelName: string | null): TargetTier {
        if (!modelName) return this.defaultTarget;

        // Get size of the requested model
        let sizeBytes = this.modelSizeCache[modelName];
        if (!sizeBytes && modelName && !modelName.includes(":")) {
            sizeBytes = this.modelSizeCache[`${modelName}:latest`];
        }
        if (!sizeBytes) {
            console.log(
                `[TargettingHandler] Model "${modelName}" not found in cache.`,
            );
            return this.defaultTarget;
        }

        // Find a pod with enough memory for the model
        for (const target of this.targets) {
            if (sizeBytes < target.size) {
                console.log(
                    `[TargettingHandler] Model "${modelName}" (${(sizeBytes / 1024 / 1024 / 1024).toFixed(2)} GB) -> Tier: ${target.name}`,
                );
                return target;
            }
        }

        // Fallback to largest pod
        const largest = this.targets[this.targets.length - 1];
        console.log(
            `[TargettingHandler] Model "${modelName}" exceeds all tier sizes. Routing to largest pod: ${largest.endpoint.origin}`,
        );
        return largest;
    }

    /**
     * Recursively checks endpoints to get what models are available and their size
     */
    updateModelCache(index: number = 0, success: boolean = false): void {
        if (index >= this.targets.length) {
            console.error(
                `[TargettingHandler] updateModelCache() called with index ${index}, which is out of bounds of available targets (${this.targets.length} targets available)`,
            );
            return;
        }

        const target = this.targets[index];
        console.log(
            `[TargettingHandler] Fetching /api/tags from ${target.endpoint.origin}`,
        );

        let nextCalled = false;
        const advance = (isSuccess: boolean = false) => {
            if (!nextCalled) {
                nextCalled = true;
                if (!isSuccess) {
                    this.updateModelCache(index + 1, success);
                }
            }
        };

        const request = http.get(
            target.endpoint.origin + "/api/tags",
            (response: http.IncomingMessage) => {
                let data = "";
                response.on("data", (chunk: string | Buffer) => {
                    data += chunk;
                });
                response.on("end", () => {
                    try {
                        const parsed = JSON.parse(data);
                        if (parsed.models) {
                            const newCache: Record<string, number> = {};
                            parsed.models.forEach(
                                (model: { name: string; size: number }) => {
                                    newCache[model.name] = model.size;
                                },
                            );
                            this.modelSizeCache = newCache;
                            success = true;
                            console.log(
                                "[TargettingHandler] Model cache refreshed successfully:",
                                Object.keys(this.modelSizeCache),
                            );
                            advance(true);
                            return;
                        }
                    } catch (e) {
                        console.error(
                            `Failed to parse /api/tags from ${target.endpoint.origin}`,
                            e,
                        );
                    }
                    advance();
                });
            },
        );
        request.on("error", advance);
        request.setTimeout(2000, () => {
            request.destroy();
            advance();
        });
    }
}
