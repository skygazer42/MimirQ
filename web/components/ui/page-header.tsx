import type { LucideIcon } from "lucide-react"
import { MANAGEMENT_HERO_PANEL_CLASS } from "@/components/ui/knowledge-ops-hero"
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
  if (compact) return "px-1 py-2"
  return "px-1 py-3"
}

function getPageHeaderGap(compact: boolean): string {
  if (compact) return "gap-2.5"
  return "gap-3"
}

function getPageHeaderIconShellClass(compact: boolean): string {
  if (compact) return "size-7 rounded-md"
  return "size-9 rounded-lg"
}

function getPageHeaderTitleClass(compact: boolean): string {
  if (compact) return "text-[19px] leading-6 tracking-[-0.02em]"
  return "text-[22px] leading-7 tracking-[-0.025em]"
}

function getPageHeaderDescriptionClass(compact: boolean): string {
  if (compact) return "text-[12px] leading-5"
  return "text-[13px] leading-5"
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
  if (iconImage) {
    return (
      <PageTitleIcon
        name={iconImage}
        compact={compact}
        className={compact ? "size-6" : "size-7"}
      />
    )
  }
  if (Icon) {
    return (
      <Icon className={cn(compact ? "size-3.5" : "size-4", iconColor)} />
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
    <header className={cn("@container flex-shrink-0 relative z-10", className)}>
      <div
        data-testid="page-title-shell"
        className={cn(
          MANAGEMENT_HERO_PANEL_CLASS,
          "flex min-h-14 flex-col gap-2 @3xl:flex-row @3xl:items-center @3xl:justify-between",
          getPageHeaderPadding(compact)
        )}
      >
        <div
          className="pointer-events-none absolute -bottom-px left-1 h-px w-12 bg-info/70"
          aria-hidden="true"
        />
        <div className={cn("relative flex min-w-0 items-center", children && "@3xl:flex-1", getPageHeaderGap(compact))}>
          {headerIcon ? (
            <div className={cn(
              "flex shrink-0 items-center justify-center border border-foreground/10 bg-background/70 text-info shadow-none",
              getPageHeaderIconShellClass(compact)
            )}>
              {headerIcon}
            </div>
          ) : null}

          <div className="min-w-0 flex-1 @2xl:flex @2xl:items-center @2xl:gap-2.5">
            <div className={cn("flex flex-wrap items-center", compact ? "gap-x-2.5 gap-y-1" : "gap-x-3 gap-y-2")}>
              {typeof title === 'string' ? (
                <h1 className={cn(
                  "text-balance text-foreground",
                  "font-semibold",
                  getPageHeaderTitleClass(compact)
                )}>
                  {title}
                </h1>
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
              <div className={cn(
                "max-w-[72ch] text-pretty text-muted-foreground/85",
                getPageHeaderDescriptionClass(compact)
              )}>
                <span>{description}</span>
              </div>
            ) : null}
          </div>
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
