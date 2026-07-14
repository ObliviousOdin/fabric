import { cn } from "../lib/utils";

const assetPath = (path: string) =>
  `${import.meta.env.BASE_URL}${path.replace(/^\/+/, "")}`;

// Canonical compact Fabric mark, without the wordmark-only bracket. The asset
// lives in this app's public/ so packaged setup builds never depend on a
// sibling checkout at runtime.
export function BrandMark({
  className,
  ...props
}: React.ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "inline-flex size-14 shrink-0 items-center justify-center",
        className,
      )}
      {...props}
    >
      <img
        alt=""
        className="size-full object-contain"
        decoding="async"
        draggable={false}
        height={512}
        src={assetPath("fabric-mark.png")}
        width={512}
      />
    </span>
  );
}
