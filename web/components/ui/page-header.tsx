import type { PlatformIcon } from '@/components/icons'
import { MANAGEMENT_HERO_PANEL_CLASS } from '@/components/ui/knowledge-ops-hero'
import { PageTitleIcon, type PageTitleIconName } from '@/components/ui/page-title-icon'
import { cn } from '@/lib/utils'

type PageHeaderProps = {
  title: React.ReactNode
  description?: React.ReactNode
  icon?: PlatformIcon
  iconImage?: PageTitleIconName
  iconColor?: string
  children?: React.ReactNode
  className?: string
  badge?: string
  status?: React.ReactNode
  compact?: boolean
}

function renderPageHeaderIcon({
  iconImage,
  Icon,
  compact,
  iconColor,
}: {
  iconImage?: PageTitleIconName
  Icon?: PlatformIcon
  compact: boolean
  iconColor: string
}) {
  if (iconImage) {
    return <PageTitleIcon name={iconImage} compact={compact} className={compact ? 'size-6' : 'size-7'} />
  }
  if (Icon) {
    return <Icon appearance="color" className={cn(compact ? 'size-3.5' : 'size-4', iconColor)} />
  }
  return null
}

export function PageHeader({
  title,
  description,
  icon: Icon,
  iconImage,
  iconColor = 'text-primary',
  children,
  className,
  badge,
  status,
  compact = true,
}: Readonly<PageHeaderProps>) {
  const paddingClass = compact ? 'px-1 py-2' : 'px-1 py-3'
  const gapClass = compact ? 'gap-2.5' : 'gap-3'
  const iconShellClass = compact ? 'size-7 rounded-md' : 'size-9 rounded-lg'
  const titleClass = compact ? 'text-[19px] leading-6 tracking-[-0.02em]' : 'text-[22px] leading-7 tracking-[-0.025em]'
  const descriptionClass = compact ? 'text-[12px] leading-5' : 'text-[13px] leading-5'
  const headerIcon = renderPageHeaderIcon({
    iconImage,
    Icon,
    compact,
    iconColor,
  })

  return (
    <header className={cn('@container flex-shrink-0 relative z-10', className)}>
      <div
        data-testid="page-title-shell"
        className={cn(
          MANAGEMENT_HERO_PANEL_CLASS,
          'flex min-h-14 flex-col gap-2 @3xl:flex-row @3xl:items-center @3xl:justify-between',
          paddingClass,
        )}
      >
        <div className="pointer-events-none absolute -bottom-px left-1 h-px w-12 bg-info/70" aria-hidden="true" />
        <div className={cn('relative flex min-w-0 items-center', (children || status) && '@3xl:flex-1', gapClass)}>
          {headerIcon ? (
            <div
              className={cn(
                'flex shrink-0 items-center justify-center border border-foreground/10 bg-background/70 text-info shadow-none',
                iconShellClass,
              )}
            >
              {headerIcon}
            </div>
          ) : null}

          <div className="min-w-0 flex-1 @2xl:flex @2xl:items-center @2xl:gap-2.5">
            <div className={cn('flex flex-wrap items-center', compact ? 'gap-x-2.5 gap-y-1' : 'gap-x-3 gap-y-2')}>
              {typeof title === 'string' ? (
                <h1 className={cn('text-balance text-foreground', 'font-semibold', titleClass)}>{title}</h1>
              ) : (
                <div className="w-full">{title}</div>
              )}
              {badge ? (
                <span className="inline-flex items-center rounded-md border border-foreground/10 bg-background/70 px-2.5 py-1 text-[11px] font-mono uppercase tracking-[0.14em] text-info tabular-nums">
                  {badge}
                </span>
              ) : null}
            </div>

            {description ? (
              <div className={cn('max-w-[72ch] text-pretty text-muted-foreground/85', descriptionClass)}>
                <span>{description}</span>
              </div>
            ) : null}
          </div>
          {status ? <div className="ml-auto shrink-0">{status}</div> : null}
        </div>

        {children ? (
          <div className="relative flex min-w-0 flex-wrap items-center justify-start gap-2 @3xl:justify-end">
            {children}
          </div>
        ) : null}
      </div>
    </header>
  )
}
