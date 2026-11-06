import Image from 'next/image'
import { BRAND_ASSETS, BRAND_NAME } from '@/lib/brand'
import { cn } from '@/lib/utils'

type BrandLogoProps = {
  className?: string
  decorative?: boolean
  priority?: boolean
  variant?: 'lockup' | 'mark'
}

export function BrandLogo({ className, decorative = false, priority = false, variant = 'lockup' }: BrandLogoProps) {
  const isMark = variant === 'mark'

  return (
    <span
      className={cn('block shrink-0 select-none', isMark ? 'aspect-square' : 'aspect-[51/16]', className)}
      role={decorative ? undefined : 'img'}
      aria-label={decorative ? undefined : BRAND_NAME}
      aria-hidden={decorative || undefined}
    >
      <Image
        src={isMark ? BRAND_ASSETS.mark : BRAND_ASSETS.logo}
        alt=""
        aria-hidden="true"
        width={isMark ? 64 : 306}
        height={isMark ? 64 : 96}
        priority={priority}
        unoptimized
        className="h-full w-full dark:hidden"
      />
      <Image
        src={isMark ? BRAND_ASSETS.markInverse : BRAND_ASSETS.logoInverse}
        alt=""
        aria-hidden="true"
        width={isMark ? 64 : 306}
        height={isMark ? 64 : 96}
        priority={priority}
        unoptimized
        className="hidden h-full w-full dark:block"
      />
    </span>
  )
}
