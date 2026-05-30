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
  teal: 'text-teal',
  orange: 'text-orange',
  red: 'text-destructive',
  gray: 'text-foreground',
  cyan: 'text-info',
  sky: 'text-info',
  rose: 'text-rose',
  indigo: 'text-indigo',
}

const iconTextStyles: Record<NonNullable<StatCardProps['color']>, string> = {
  amber: 'text-warning/80',
  blue: 'text-info/80',
  green: 'text-success/80',
  teal: 'text-teal/80',
  orange: 'text-orange/80',
  red: 'text-destructive/80',
  gray: 'text-muted-foreground',
  cyan: 'text-info/80',
  sky: 'text-info/80',
  rose: 'text-rose/80',
  indigo: 'text-indigo/80',
}

const colorStyles = {
  amber: 'border-warning/20 bg-warning/5 text-warning group-hover:border-warning/40 group-hover:bg-warning/10',
  blue: 'border-info/20 bg-info/5 text-info group-hover:border-info/40 group-hover:bg-info/10',
  green: 'border-success/20 bg-success/5 text-success group-hover:border-success/40 group-hover:bg-success/10',
  teal: 'border-teal/20 bg-teal/5 text-teal group-hover:border-teal/40 group-hover:bg-teal/10',
  orange: 'border-orange/20 bg-orange/5 text-orange group-hover:border-orange/40 group-hover:bg-orange/10',
  red: 'border-destructive/20 bg-destructive/5 text-destructive group-hover:border-destructive/40 group-hover:bg-destructive/10',
  gray: 'border-border bg-muted/40 text-muted-foreground group-hover:bg-muted/60',
  cyan: 'border-primary/20 bg-primary/5 text-primary group-hover:border-primary/40 group-hover:bg-primary/10',
  sky: 'border-info/20 bg-info/5 text-info group-hover:border-info/40 group-hover:bg-info/10',
  rose: 'border-rose/20 bg-rose/5 text-rose group-hover:border-rose/40 group-hover:bg-rose/10',
  indigo: 'border-indigo/20 bg-indigo/5 text-indigo group-hover:border-indigo/40 group-hover:bg-indigo/10',
}

const iconBgStyles = {
  amber: 'bg-warning/15 text-warning group-hover:bg-warning/25',
  blue: 'bg-info/15 text-info group-hover:bg-info/25',
  green: 'bg-success/15 text-success group-hover:bg-success/25',
  teal: 'bg-teal/15 text-teal group-hover:bg-teal/25',
  orange: 'bg-orange/15 text-orange group-hover:bg-orange/25',
  red: 'bg-destructive/15 text-destructive group-hover:bg-destructive/25',
  gray: 'bg-muted/80 text-muted-foreground group-hover:bg-muted',
  cyan: 'bg-primary/15 text-primary group-hover:bg-primary/25',
  sky: 'bg-info/15 text-info group-hover:bg-info/25',
  rose: 'bg-rose/15 text-rose group-hover:bg-rose/25',
  indigo: 'bg-indigo/15 text-indigo group-hover:bg-indigo/25',
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
      ? "bg-muted/40 text-muted-foreground/60 border-border/40"
      : active
        ? "bg-primary/10 text-primary border-primary/20 shadow-[0_0_12px_-4px_rgba(var(--primary),0.2)]"
        : (colorStyles[color] || colorStyles.sky) + " border-border/30"

    return (
      <Wrapper
        onClick={onClick}
        type={onClick ? 'button' : undefined}
        className={cn(
          "inline-flex items-center gap-2 h-8 px-2.5 rounded-xl group/stat transition-all duration-300 text-left whitespace-nowrap border shadow-none",
          onClick && "cursor-pointer hover:shadow-soft",
          statusColorStyle,
          className,
        )}
      >
        <div className={cn(
          "relative flex size-5 shrink-0 items-center justify-center rounded-lg transition-all duration-500",
          isDimmed
            ? "bg-muted/40 text-muted-foreground/70"
            : active
              ? "bg-primary/20 text-primary"
              : (iconBgStyles[color] || iconBgStyles.sky)
        )}>
          <Icon className="size-3.5" />
          {dot && !isDimmed && (
            <span className={cn("absolute -right-0.5 -top-0.5 inline-block size-1.5 rounded-full ring-2 ring-background", dotStyles[dot])} />
          )}
        </div>
        <div className="flex flex-col">
          <span className="text-[9px] font-black uppercase  opacity-60 leading-none mb-0.5">
            {label}
          </span>
          <div className="flex items-baseline gap-1">
            <span className={cn(
              "text-[13px] font-black font-mono tabular-nums leading-none transition-all duration-500",
              isDimmed ? "text-foreground/50 font-bold" : "text-foreground"
            )}>
              {value}
            </span>
            {unit && (
              <span className={cn(
                "text-[9px] font-bold uppercase  transition-opacity duration-500",
                isDimmed ? "opacity-30" : "opacity-40"
              )}>
                {unit}
              </span>
            )}
          </div>
        </div>
      </Wrapper>
    )
  }

  const silentColorStyle = 'border-border/60 bg-muted/10 text-muted-foreground/80'
  const silentIconStyle = 'bg-muted/20 text-muted-foreground/60'

  if (dense) {
    return (
      <div className={cn(
        'group flex items-center gap-3 rounded-xl border px-3 py-1.5 transition-all duration-500 backdrop-blur-md',
        isDimmed ? silentColorStyle : (colorStyles[color] || colorStyles.sky) + ' bg-card/30',
        className
      )}>
        <div className={cn('flex size-7 items-center justify-center rounded-lg transition-all duration-500', isDimmed ? silentIconStyle : (iconBgStyles[color] || iconBgStyles.sky))}>
          <Icon className="size-3.5" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-[9px] font-black uppercase  text-muted-foreground/60">{label}</p>
          <p className={cn("truncate text-sm font-mono tabular-nums transition-all duration-500", isDimmed ? "font-black text-foreground/70" : "font-black text-foreground/80")}>{value}</p>
        </div>
      </div>
    )
  }

  return (
    <div className={cn(
      'group relative overflow-hidden transition-all duration-500',
      'flex items-center gap-4 rounded-2xl border px-5 py-4 shadow-subtle hover:shadow-soft',
      isDimmed ? silentColorStyle : (colorStyles[color] || colorStyles.sky),
      className
    )}>
      <div className={cn('relative flex items-center justify-center transition-all duration-500 size-11 rounded-xl p-2.5', isDimmed ? silentIconStyle : (iconBgStyles[color] || iconBgStyles.sky))}>
        <Icon className="size-5" />
      </div>
      <div className="relative min-w-0 flex-1">
        <p className="truncate text-[11px] font-black uppercase  mb-1 text-muted-foreground/60">{label}</p>
        <div className="flex items-baseline gap-2">
          <p className={cn("truncate text-[22px] font-mono font-black  leading-none transition-all duration-500", isDimmed ? "text-foreground/70 font-black" : "text-foreground")}>{value}</p>
          {unit && <span className="text-xs font-bold uppercase text-muted-foreground/40 transition-all duration-500">{unit}</span>}
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
