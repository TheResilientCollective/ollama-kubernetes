import * as http from "http";

export interface TargetTier {
    name: string;
    endpoint: URL;
    size: number; // in bytes
    headlessDns: string;
}
