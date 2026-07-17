import { useState } from "react";

import { cn } from "@/lib/utils";
import {
  FABRIC_BRAND_ASSETS,
  resolveFabricBrandAsset,
} from "./brand-assets";

interface FabricBrandProps extends Omit<
  React.ComponentProps<"span">,
  "children"
> {
  appearance: "dark" | "light";
  compact?: boolean;
  label?: string;
}

/**
 * Responsive Fabric brand lockup for application chrome.
 *
 * The image is decorative because the adjacent visually-hidden text carries
 * the accessible label. Fixed intrinsic and rendered dimensions keep the
 * sidebar header stable while the asset loads or falls back to text.
 */
export function FabricBrand({
  appearance,
  className,
  compact = false,
  label = "Fabric",
  ...props
}: FabricBrandProps) {
  const assetPath = compact
    ? FABRIC_BRAND_ASSETS.mark
    : appearance === "dark"
      ? FABRIC_BRAND_ASSETS.wordmarkOnDark
      : FABRIC_BRAND_ASSETS.wordmark;
  const src = resolveFabricBrandAsset(assetPath);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const showFallback = failedSrc === src;

  return (
    <span
      {...props}
      className={cn(
        "inline-flex shrink-0 items-center justify-center overflow-hidden",
        compact ? "size-[1.125rem]" : "h-8 w-[5.8125rem]",
        className,
      )}
      data-compact={compact ? "true" : "false"}
      data-fabric-brand="true"
    >
      <span className="sr-only">{label}</span>

      {showFallback ? (
        <span
          aria-hidden="true"
          className={cn(
            "font-sans font-semibold leading-none",
            compact
              ? "text-lg text-[var(--fabric-brand-primary)]"
              : "text-[1.125rem] tracking-[-0.015em] text-midground",
          )}
          data-brand-fallback="true"
        >
          {compact ? "F" : label}
        </span>
      ) : (
        <img
          alt=""
          aria-hidden="true"
          className={compact ? "size-[1.125rem]" : "h-8 w-[5.8125rem]"}
          draggable={false}
          height={compact ? 18 : 32}
          onError={() => setFailedSrc(src)}
          src={src}
          width={compact ? 18 : 93}
        />
      )}
    </span>
  );
}
