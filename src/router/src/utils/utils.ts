/**
 * Parses a string like "3Gi" into number of bytes
 * @param (string) sizeStr: the string like "3.2Gi" to parse
 * @returns (number) the number of bytes that corresponds to the parsed sizeStr or 0
 */
export function parseK8sSize(sizeStr: string): number {
    if (!sizeStr) return 0;
    const match = sizeStr.trim().match(/^(\d+(?:\.\d+)?)\s*([a-zA-Z]+)?$/);
    if (!match || match.length !== 3) return 0;
    const value = parseFloat(match[1]);
    const unit = match[2].toLowerCase();
    switch (unit) {
        case "ti":
        case "tib":
            return value * 1024 * 1024 * 1024 * 1024;
        case "t":
        case "tb":
            return value * 1000 * 1000 * 1000 * 1000;
        case "gi":
        case "gib":
            return value * 1024 * 1024 * 1024;
        case "g":
        case "gb":
            return value * 1000 * 1000 * 1000;
        case "mi":
        case "mib":
            return value * 1024 * 1024;
        case "m":
        case "mb":
            return value * 1000 * 1000;
        case "ki":
        case "kib":
            return value * 1024;
        case "k":
        case "kb":
            return value * 1000;
        default:
            return value;
    }
}
