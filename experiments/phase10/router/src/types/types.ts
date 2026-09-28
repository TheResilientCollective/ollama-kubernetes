export interface TargetTier {
    name: string;
    endpoint: URL;
    size: number; // in bytes
    headlessDns: string;
}

export interface QueueSnapshotItem {
    modelName: string;
    queuedDurationMs: number;
    createdAt: number;
}

export interface QueueSnapshot {
    [key: string]: {
        length: number;
        items: QueueSnapshotItem[];
    };
}

export interface PodSnapshot {
    ip: string;
    activeRequests: number;
    loadedModels: string[];
    lastPolledMsAgo: number;
}

export interface PodStateSnapshot {
    [key: string]: PodSnapshot[];
}
