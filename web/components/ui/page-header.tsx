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
  if (compact) return "px-4 py-3"
  return "px-5 py-5 md:px-6"
}

function getPageHeaderGap(compact: boolean): string {
  if (compact) return "gap-3"
  return "gap-4"
}

function getPageHeaderIconShellClass(compact: boolean): string {
  if (compact) return "size-14 rounded-2xl"
  return "size-14 rounded-[22px]"
}

function getPageHeaderTitleClass(compact: boolean): string {
  if (compact) return "text-[26px] leading-tight tracking-[-0.025em]"
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
  if (iconImage) {
    return (
      <PageTitleIcon
        name={iconImage}
        compact={compact}
        className={compact ? "size-9" : undefined}
      />
    )
  }
  if (Icon) {
    return (
      <Icon className={cn(compact ? "size-5" : "size-6", iconColor)} />
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
          compact && "min-h-[95px]",
          "flex flex-col gap-3 @3xl:flex-row @3xl:items-center @3xl:justify-between",
          getPageHeaderPadding(compact)
        )}
      >
        <div
          className="pointer-events-none absolute bottom-0 left-8 right-8 h-px bg-[linear-gradient(90deg,transparent,hsl(var(--info)/0.28),transparent)]"
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute -right-10 -top-14 size-44 rounded-full bg-info/10 blur-3xl dark:bg-info/[0.08]"
          aria-hidden="true"
        />
        <div className={cn("relative flex min-w-0 items-center", children && "@3xl:flex-1", getPageHeaderGap(compact))}>
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
                  "text-balance text-foreground",
                  compact ? "font-black" : "font-semibold",
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
                "max-w-[72ch] text-pretty text-muted-foreground",
                getPageHeaderDescriptionClass(compact)
              )}>
                <span>{description}</span>
              </div>
            ) : null}
          </div>
        </div>

        {children ? (
          <div className={cn("relative flex min-w-0 flex-wrap items-center justify-start gap-2 @3xl:justify-end", getPageHeaderActionsClass(compact))}>
            {children}
          </div>
        ) : null}
      </div>
    </header>
  )
}
