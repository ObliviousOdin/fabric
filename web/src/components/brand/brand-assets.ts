import { HERMES_BASE_PATH } from "@/lib/api";

export const FABRIC_BRAND_ASSETS = {
  mark: "/brand/fabric-mark.svg",
  wordmark: "/brand/fabric-wordmark.svg",
  wordmarkOnDark: "/brand/fabric-wordmark-on-dark.svg",
} as const;

export function resolveFabricBrandAsset(
  assetPath: string,
  basePath = HERMES_BASE_PATH,
): string {
  return `${basePath}${assetPath}`;
}
