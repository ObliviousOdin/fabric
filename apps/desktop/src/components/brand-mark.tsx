import { desktopBrand } from '@/brand'
import { cn } from '@/lib/utils'

const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

// Build-selected compact Fabric app mark. The deterministic source icon already
// carries its own neutral tile, so the wrapper only supplies platform-like
// corner clipping. Size via className (default size-14).
export function BrandMark({ className, ...props }: React.ComponentProps<'span'>) {
  return (
    <span
      className={cn(
        'inline-flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-[22%] bg-transparent',
        className
      )}
      {...props}
    >
      <img
        alt=""
        className="size-full object-contain"
        decoding="async"
        draggable={false}
        height={512}
        src={assetPath(desktopBrand.iconAsset)}
        width={512}
      />
    </span>
  )
}
