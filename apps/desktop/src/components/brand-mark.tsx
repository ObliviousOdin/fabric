import { desktopBrand } from '@/brand'
import { cn } from '@/lib/utils'

import fabricWordmarkDark from '../../../design-system/src/brand/fabric/wordmark-on-dark.svg?url'
import fabricWordmarkLight from '../../../design-system/src/brand/fabric/wordmark.svg?url'

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

// The full Fabric wordmark preserves the bracket underline from the canonical
// brand source. Use it for hero moments; compact surfaces should use BrandMark.
export function BrandWordmark({ className, ...props }: React.ComponentProps<'span'>) {
  return (
    <span
      aria-label={desktopBrand.productName}
      className={cn('inline-flex shrink-0 items-center justify-center', className)}
      role="img"
      {...props}
    >
      <img alt="" className="h-auto w-full dark:hidden" decoding="async" draggable={false} src={fabricWordmarkLight} />
      <img
        alt=""
        className="hidden h-auto w-full dark:block"
        decoding="async"
        draggable={false}
        src={fabricWordmarkDark}
      />
    </span>
  )
}
