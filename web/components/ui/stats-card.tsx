'use client'

import { cn } from '@/lib/utils'
import { LucideIcon } from 'lucide-react'

interface StatCardProps {
  icon: LucideIcon
  label: string
  value: string | number
  subValue?: string
  unit?: string
  dot?: 'success' | 'warning' | 'destructive' | 'info' | 'pulse'
  dim?: boolean
  onClick?: () => void
  active?: boolean
  color?: 'amber' | 'blue' | 'green' | 'teal' | 'orange' | 'red' | 'gray' | 'cyan' | 'sky' | 'rose' | 'indigo'
  className?: string
  dense?: boolean
}

const dotStyles: Record<NonNullable<StatCardProps['dot']>, string> = {
  success: 'bg-success',
  warning: 'bg-warning',
  destructive: 'bg-destructive',
  info: 'bg-info',
  pulse: 'bg-info animate-pulse',
}

const valueColorStyles: Record<NonNullable<StatCardProps['color']>, string> = {
  amber: 'text-warning',
  blue: 'text-info',
  green: 'text-success',
  teal: 'text-success',
  orange: 'text-warning',
  red: 'text-destructive',
  gray: 'text-foreground',
  cyan: 'text-info',
  sky: 'text-info',
  rose: 'text-destructive',
  indigo: 'text-primary',
}

const iconTextStyles: Record<NonNullable<StatCardProps['color']>, string> = {
  amber: 'text-warning/80',
  blue: 'text-info/80',
  green: 'text-success/80',
  teal: 'text-success/80',
  orange: 'text-warning/80',
  red: 'text-destructive/80',
  gray: 'text-muted-foreground',
  cyan: 'text-info/80',
  sky: 'text-info/80',
  rose: 'text-destructive/80',
  indigo: 'text-primary/80',
}

const colorStyles = {
  amber: 'border-warning/20 bg-background text-warning group-hover:border-warning/30 group-hover:bg-warning/[0.06]',
  blue: 'border-info/20 bg-background text-info group-hover:border-info/30 group-hover:bg-info/[0.06]',
  green: 'border-success/20 bg-background text-success group-hover:border-success/30 group-hover:bg-success/[0.06]',
  teal: 'border-success/20 bg-background text-success group-hover:border-success/30 group-hover:bg-success/[0.05]',
  orange: 'border-warning/20 bg-background text-warning group-hover:border-warning/30 group-hover:bg-warning/[0.05]',
  red: 'border-destructive/18 bg-background text-destructive group-hover:border-destructive/28 group-hover:bg-destructive/[0.05]',
  gray: 'border-foreground/10 bg-background text-foreground group-hover:border-foreground/15 group-hover:bg-muted/18',
  cyan: 'border-info/20 bg-background text-info group-hover:border-info/30 group-hover:bg-info/[0.06]',
  sky: 'border-info/20 bg-background text-info group-hover:border-info/30 group-hover:bg-info/[0.06]',
  rose: 'border-destructive/18 bg-background text-destructive group-hover:border-destructive/28 group-hover:bg-destructive/[0.05]',
  indigo: 'border-primary/20 bg-background text-primary group-hover:border-primary/30 group-hover:bg-primary/[0.06]',
}

const iconBgStyles = {
  amber: 'border border-warning/20 bg-warning/[0.08] text-warning',
  blue: 'border border-info/20 bg-info/[0.08] text-info',
  green: 'border border-success/20 bg-success/[0.08] text-success',
  teal: 'border border-success/20 bg-success/[0.07] text-success',
  orange: 'border border-warning/20 bg-warning/[0.07] text-warning',
  red: 'border border-destructive/20 bg-destructive/[0.07] text-destructive',
  gray: 'border border-foreground/10 bg-muted/18 text-muted-foreground',
  cyan: 'border border-info/20 bg-info/[0.08] text-info',
  sky: 'border border-info/20 bg-info/[0.08] text-info',
  rose: 'border border-destructive/20 bg-destructive/[0.07] text-destructive',
  indigo: 'border border-primary/20 bg-primary/[0.08] text-primary',
}

export function StatCard({
  icon: Icon,
  label,
  value,
  subValue,
  unit,
  dot,
  dim,
  onClick,
  active = false,
  color = 'sky',
  className,
  dense = false,
  variant = 'default',
}: Readonly<StatCardProps & { variant?: 'default' | 'minimal' }>) {
  const isZeroValue = value === 0 || value === '0' || value === '0 Bytes' || value === '' || value == null
  const isDimmed = dim ?? isZeroValue

  if (variant === 'minimal') {
    const Wrapper = onClick ? 'button' : 'div'
    const statusColorStyle = isDimmed
      ? "bg-muted/18 text-muted-foreground border-foreground/10"
      : active
        ? "bg-info/[0.08] text-info border-info/28"
        : (colorStyles[color] || colorStyles.sky) + " border-info/30"

    return (
      <Wrapper
        onClick={onClick}
        type={onClick ? 'button' : undefined}
        className={cn(
          "inline-flex items-center gap-2.5 h-9 px-3 rounded-full group/stat transition-colors duration-200 text-left whitespace-nowrap border bg-background",
          onClick && "cursor-pointer hover:border-primary/18 hover:bg-muted/18",
          statusColorStyle,
          className,
        )}
      >
        <div className={cn(
          "relative flex size-6 shrink-0 items-center justify-center rounded-md transition-colors duration-200",
          isDimmed
            ? "border border-foreground/10 bg-muted/18 text-muted-foreground/70"
            : active
              ? "border border-info/20 bg-info/[0.08] text-info"
              : (iconBgStyles[color] || iconBgStyles.sky)
        )}>
          <Icon className="size-4" />
          {dot && !isDimmed && (
            <span className={cn("absolute -right-0.5 -top-0.5 inline-block size-2 rounded-full ring-2 ring-background shadow-sm", dotStyles[dot])} />
          )}
        </div>
        <div className="flex flex-col">
          <span className="text-[9px] font-black uppercase opacity-70 leading-none mb-0.5">
            {label}
          </span>
          <div className="flex items-baseline gap-1">
            <span className={cn(
              "text-[14px] font-black font-mono tabular-nums leading-none transition-all duration-200",
              isDimmed ? "text-muted-foreground" : "text-foreground"
            )}>
              {value}
            </span>
            {unit && (
              <span className={cn(
                "text-[9px] font-bold uppercase transition-opacity duration-200",
                isDimmed ? "opacity-40" : "opacity-60"
              )}>
                {unit}
              </span>
            )}
          </div>
        </div>
      </Wrapper>
    )
  }

  const silentColorStyle = 'border-foreground/10 bg-muted/18 text-muted-foreground'
  const silentIconStyle = 'border border-foreground/10 bg-muted/18 text-muted-foreground/70'

  if (dense) {
    return (
      <div className={cn(
        'group flex items-center gap-3 rounded-xl border border-foreground/10 bg-background px-3 py-2 shadow-none transition-colors duration-200 hover:border-primary/18 hover:bg-muted/18',
        isDimmed ? silentColorStyle : colorStyles[color] || colorStyles.sky,
        className
      )}>
        <div className={cn('flex size-8 items-center justify-center rounded-lg transition-colors duration-200', isDimmed ? silentIconStyle : (iconBgStyles[color] || iconBgStyles.sky))}>
          <Icon className="size-4" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-[10px] font-black uppercase text-muted-foreground">{label}</p>
          <p className={cn("truncate text-[14px] font-mono font-black tabular-nums transition-all duration-200", isDimmed ? "text-muted-foreground" : "text-foreground")}>{value}</p>
        </div>
      </div>
    )
  }

  return (
    <div className={cn(
      'group relative overflow-hidden transition-all duration-200',
      'flex items-center gap-4 rounded-xl border border-foreground/10 bg-background px-5 py-4 shadow-none hover:border-primary/18',
      isDimmed ? silentColorStyle : (colorStyles[color] || colorStyles.sky),
      className
    )}>
      <div className={cn('relative flex size-12 items-center justify-center rounded-lg p-3 transition-colors duration-200', isDimmed ? silentIconStyle : (iconBgStyles[color] || iconBgStyles.sky))}>
        <Icon className="size-6" />
      </div>
      <div className="relative min-w-0 flex-1">
        <p className="truncate text-[11px] font-black uppercase mb-1 text-muted-foreground">{label}</p>
        <div className="flex items-baseline gap-2">
          <p className={cn("truncate text-[24px] font-mono font-black leading-none transition-all duration-200", isDimmed ? "text-muted-foreground" : "text-foreground")}>{value}</p>
          {unit && <span className="text-xs font-bold uppercase text-muted-foreground transition-all duration-200">{unit}</span>}
        </div>
      </div>
    </div>
  )
}

export function StatsGrid({ children, className, dense = false }: Readonly<{ children: React.ReactNode; className?: string; dense?: boolean }>) {
  return (
    <div className={cn(
      dense
        ? 'grid grid-cols-1 gap-2 md:gap-3 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6'
        : 'grid grid-cols-1 gap-3 md:gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5',
      className
    )}>
      {children}
    </div>
  )
}
