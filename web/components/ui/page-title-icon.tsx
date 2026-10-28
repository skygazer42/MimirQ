import { PAGE_TITLE_ICONS } from '@/components/icons/page-icons'
import { cn } from '@/lib/utils'

export type PageTitleIconName = keyof typeof PAGE_TITLE_ICONS
export const PAGE_TITLE_ICON_NAMES = Object.keys(PAGE_TITLE_ICONS) as PageTitleIconName[]

type PageTitleIconProps = {
  name: PageTitleIconName
  compact?: boolean
  className?: string
}

export function PageTitleIcon({
  name,
  compact = true,
  className,
}: Readonly<PageTitleIconProps>) {
  const Icon = PAGE_TITLE_ICONS[name]
  return (
    <Icon
      appearance="color"
      aria-hidden="true"
      data-page-title-icon={name}
      className={cn('pointer-events-none select-none text-current', compact ? 'size-8' : 'size-10', className)}
    />
  )
}
