import { cn } from "../lib/utils";

const assetPath = (path: string) =>
  `${import.meta.env.BASE_URL}${path.replace(/^\/+/, "")}`;

// Original Fabric mark, kept identical in light and dark themes. The asset
// lives in this app's public/ so packaged setup builds
// never depend on a sibling checkout at runtime.
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
        src={assetPath("fabric-mark.png")}
      />
    </span>
  );
}
