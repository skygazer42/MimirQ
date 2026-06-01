import type { LucideIcon } from "lucide-react"
import { PageTitleIcon, type PageTitleIconName } from "@/components/ui/page-title-icon"
import { cn } from "@/lib/utils"

interface PageHeaderProps {
  title: React.ReactNode
  description?: React.ReactNode
  icon?: LucideIcon
  iconImage?: PageTitleIconName
  iconColor?: string
  children?: React.ReactNode
  className?: string
  badge?: string
  compact?: boolean
}

function getPageHeaderPadding(compact: boolean): string {
  if (compact) return "px-4 py-3"
  return "px-5 py-5 md:px-6"
}

function getPageHeaderGap(compact: boolean): string {
  if (compact) return "gap-3"
  return "gap-4"
}

function getPageHeaderIconShellClass(compact: boolean): string {
  if (compact) return "size-11 rounded-[18px]"
  return "size-14 rounded-[22px]"
}

function getPageHeaderTitleClass(compact: boolean): string {
  if (compact) return "text-lg md:text-xl leading-snug tracking-[-0.01em]"
  return "text-4xl md:text-5xl leading-[1.02] tracking-[-0.03em]"
}

function getPageHeaderDescriptionClass(compact: boolean): string {
  if (compact) return "mt-0.5 text-[13px] leading-relaxed md:text-sm"
  return "mt-2 text-sm leading-[1.75] md:text-[15px]"
}

function getPageHeaderActionsClass(compact: boolean): string {
  if (compact) return "pt-0"
  return "pt-1"
}

function renderPageHeaderIcon({
  iconImage,
  Icon,
  compact,
  iconColor,
}: {
  iconImage?: PageTitleIconName
  Icon?: LucideIcon
  compact: boolean
  iconColor: string
}) {
  if (iconImage) return <PageTitleIcon name={iconImage} compact={compact} />
  if (Icon) {
    return (
      <Icon className={cn(compact ? "size-[18px]" : "size-6", iconColor)} />
    )
  }
  return null
}

export function PageHeader({
  title,
  description,
  icon: Icon,
  iconImage,
  iconColor = "text-primary",
  children,
  className,
  badge,
  compact = true,
}: Readonly<PageHeaderProps>) {
  const headerIcon = renderPageHeaderIcon({
    iconImage,
    Icon,
    compact,
    iconColor,
  })

  return (
    <header className={cn("flex-shrink-0 relative z-10", className)}>
      <div
        data-testid="page-title-shell"
        className={cn(
          "relative overflow-hidden rounded-[24px] border border-border/70 bg-[linear-gradient(135deg,hsl(var(--card)/0.98),hsl(var(--muted)/0.34))] shadow-[0_18px_46px_-40px_hsl(var(--foreground)/0.46)]",
          "flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between",
          getPageHeaderPadding(compact)
        )}
      >
        <div
          className="pointer-events-none absolute inset-y-3 left-0 w-1 rounded-r-full bg-[linear-gradient(180deg,hsl(var(--info)),hsl(var(--primary)))]"
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute -right-10 -top-12 size-32 rounded-full bg-info/10 blur-2xl"
          aria-hidden="true"
        />
        <div className={cn("relative flex items-center min-w-0", getPageHeaderGap(compact))}>
          {headerIcon ? (
            <div className={cn(
              "shrink-0 flex items-center justify-center border border-info/18 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--info)/0.10))] shadow-[inset_0_1px_0_hsl(var(--background)),0_14px_30px_-24px_hsl(var(--info)/0.75)]",
              getPageHeaderIconShellClass(compact)
            )}>
              {headerIcon}
            </div>
          ) : null}

          <div className="min-w-0 flex-1">
            <div className={cn("flex flex-wrap items-center", compact ? "gap-x-2.5 gap-y-1" : "gap-x-3 gap-y-2")}>
              {typeof title === 'string' ? (
                <h1 className={cn(
                  "text-balance font-semibold text-foreground",
                  getPageHeaderTitleClass(compact)
                )}>
                  <span className="bg-[linear-gradient(90deg,hsl(var(--foreground)),hsl(var(--info))_92%)] bg-clip-text text-transparent">
                    {title}
                  </span>
                </h1>
              ) : (
                <div className="w-full">{title}</div>
              )}
              {badge ? (
                <span className="inline-flex items-center rounded-full border border-info/18 bg-info/[0.08] px-2.5 py-1 text-[11px] font-mono uppercase tracking-[0.14em] text-info tabular-nums backdrop-blur-xl">
                  {badge}
                </span>
              ) : null}
            </div>

            {description ? (
              <div className={cn(
                "flex max-w-[72ch] items-start gap-2 text-pretty text-muted-foreground",
                getPageHeaderDescriptionClass(compact)
              )}>
                <span className="mt-[0.7em] size-1.5 shrink-0 rounded-full bg-info/55 shadow-[0_0_0_4px_hsl(var(--info)/0.08)]" />
                <span>{description}</span>
              </div>
            ) : null}
          </div>
        </div>

        {children ? <div className={cn("relative flex items-center gap-2", getPageHeaderActionsClass(compact))}>{children}</div> : null}
      </div>
    </header>
  )
}
