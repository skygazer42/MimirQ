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
  amber: 'border-warning/20 bg-[linear-gradient(135deg,hsl(var(--background)/0.94),hsl(var(--warning)/0.12))] text-warning group-hover:border-warning/30 group-hover:bg-[linear-gradient(135deg,hsl(var(--background)/0.98),hsl(var(--warning)/0.18))]',
  blue: 'border-info/20 bg-[linear-gradient(135deg,hsl(var(--background)/0.94),hsl(var(--info)/0.12))] text-info group-hover:border-info/30 group-hover:bg-[linear-gradient(135deg,hsl(var(--background)/0.98),hsl(var(--info)/0.18))]',
  green: 'border-success/20 bg-[linear-gradient(135deg,hsl(var(--background)/0.94),hsl(var(--success)/0.12))] text-success group-hover:border-success/30 group-hover:bg-[linear-gradient(135deg,hsl(var(--background)/0.98),hsl(var(--success)/0.18))]',
  teal: 'border-success/20 bg-[linear-gradient(135deg,hsl(var(--background)/0.94),hsl(var(--success)/0.10))] text-success group-hover:border-success/30 group-hover:bg-[linear-gradient(135deg,hsl(var(--background)/0.98),hsl(var(--success)/0.16))]',
  orange: 'border-warning/20 bg-[linear-gradient(135deg,hsl(var(--background)/0.94),hsl(var(--warning)/0.10))] text-warning group-hover:border-warning/30 group-hover:bg-[linear-gradient(135deg,hsl(var(--background)/0.98),hsl(var(--warning)/0.16))]',
  red: 'border-destructive/18 bg-[linear-gradient(135deg,hsl(var(--background)/0.94),hsl(var(--destructive)/0.10))] text-destructive group-hover:border-destructive/28 group-hover:bg-[linear-gradient(135deg,hsl(var(--background)/0.98),hsl(var(--destructive)/0.16))]',
  gray: 'border-border/60 bg-[linear-gradient(135deg,hsl(var(--background)/0.94),hsl(var(--muted)/0.42))] text-foreground group-hover:border-border/70 group-hover:bg-[linear-gradient(135deg,hsl(var(--background)/0.98),hsl(var(--muted)/0.52))]',
  cyan: 'border-info/20 bg-[linear-gradient(135deg,hsl(var(--background)/0.94),hsl(var(--info)/0.12))] text-info group-hover:border-info/30 group-hover:bg-[linear-gradient(135deg,hsl(var(--background)/0.98),hsl(var(--info)/0.18))]',
  sky: 'border-info/20 bg-[linear-gradient(135deg,hsl(var(--background)/0.94),hsl(var(--info)/0.12))] text-info group-hover:border-info/30 group-hover:bg-[linear-gradient(135deg,hsl(var(--background)/0.98),hsl(var(--info)/0.18))]',
  rose: 'border-destructive/18 bg-[linear-gradient(135deg,hsl(var(--background)/0.94),hsl(var(--destructive)/0.10))] text-destructive group-hover:border-destructive/28 group-hover:bg-[linear-gradient(135deg,hsl(var(--background)/0.98),hsl(var(--destructive)/0.16))]',
  indigo: 'border-primary/20 bg-[linear-gradient(135deg,hsl(var(--background)/0.94),hsl(var(--primary)/0.12))] text-primary group-hover:border-primary/30 group-hover:bg-[linear-gradient(135deg,hsl(var(--background)/0.98),hsl(var(--primary)/0.18))]',
}

const iconBgStyles = {
  amber: 'bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--warning)/0.16))] text-warning',
  blue: 'bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--info)/0.16))] text-info',
  green: 'bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--success)/0.16))] text-success',
  teal: 'bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--success)/0.14))] text-success',
  orange: 'bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--warning)/0.14))] text-warning',
  red: 'bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--destructive)/0.14))] text-destructive',
  gray: 'bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.44))] text-muted-foreground',
  cyan: 'bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--info)/0.16))] text-info',
  sky: 'bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--info)/0.16))] text-info',
  rose: 'bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--destructive)/0.14))] text-destructive',
  indigo: 'bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--primary)/0.16))] text-primary',
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
      ? "bg-muted/60 text-muted-foreground border-border/60"
      : active
        ? "bg-[linear-gradient(90deg,hsl(var(--background)/0.92),hsl(var(--info)/0.18))] text-info border-info/28 shadow-md shadow-[0_12px_24px_-18px_hsl(var(--info)/0.45)]"
        : (colorStyles[color] || colorStyles.sky) + " border-info/30 shadow-sm"

    return (
      <Wrapper
        onClick={onClick}
        type={onClick ? 'button' : undefined}
        className={cn(
          "inline-flex items-center gap-2.5 h-9 px-3 rounded-full group/stat transition-all duration-200 text-left whitespace-nowrap border backdrop-blur-sm",
          onClick && "cursor-pointer hover:shadow-md hover:scale-105",
          statusColorStyle,
          className,
        )}
      >
        <div className={cn(
          "relative flex size-6 shrink-0 items-center justify-center rounded-lg transition-all duration-200",
          isDimmed
            ? "bg-muted text-muted-foreground/70"
            : active
              ? "bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--info)/0.22))] text-info"
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

  const silentColorStyle = 'border-border/60 bg-muted/40 text-muted-foreground'
  const silentIconStyle = 'bg-muted/60 text-muted-foreground/70'

  if (dense) {
    return (
      <div className={cn(
        'group flex items-center gap-3 rounded-2xl border px-3 py-2 shadow-sm backdrop-blur-sm transition-all duration-200 hover:shadow-md',
        isDimmed ? silentColorStyle : colorStyles[color] || colorStyles.sky,
        className
      )}>
        <div className={cn('flex size-8 items-center justify-center rounded-xl shadow-sm transition-all duration-200 group-hover:scale-110', isDimmed ? silentIconStyle : (iconBgStyles[color] || iconBgStyles.sky))}>
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
      'flex items-center gap-4 rounded-2xl border px-5 py-4 shadow-md backdrop-blur-sm hover:shadow-lg hover:scale-[1.02]',
      isDimmed ? silentColorStyle : (colorStyles[color] || colorStyles.sky),
      className
    )}>
      <div className={cn('relative flex items-center justify-center transition-all duration-200 size-12 rounded-xl p-3 shadow-sm group-hover:scale-110', isDimmed ? silentIconStyle : (iconBgStyles[color] || iconBgStyles.sky))}>
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
