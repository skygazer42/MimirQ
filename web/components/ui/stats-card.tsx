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
  amber: 'border-amber-200/50 bg-gradient-to-br from-amber-50/40 to-orange-50/30 text-amber-700 group-hover:border-amber-300 group-hover:from-amber-50/60 group-hover:to-orange-50/50',
  blue: 'border-sky-200/50 bg-gradient-to-br from-sky-50/40 to-blue-50/30 text-sky-700 group-hover:border-sky-300 group-hover:from-sky-50/60 group-hover:to-blue-50/50',
  green: 'border-emerald-200/50 bg-gradient-to-br from-emerald-50/40 to-teal-50/30 text-emerald-700 group-hover:border-emerald-300 group-hover:from-emerald-50/60 group-hover:to-teal-50/50',
  teal: 'border-teal-200/50 bg-gradient-to-br from-teal-50/40 to-cyan-50/30 text-teal-700 group-hover:border-teal-300 group-hover:from-teal-50/60 group-hover:to-cyan-50/50',
  orange: 'border-orange-200/50 bg-gradient-to-br from-orange-50/40 to-amber-50/30 text-orange-700 group-hover:border-orange-300 group-hover:from-orange-50/60 group-hover:to-amber-50/50',
  red: 'border-rose-200/50 bg-gradient-to-br from-rose-50/40 to-pink-50/30 text-rose-700 group-hover:border-rose-300 group-hover:from-rose-50/60 group-hover:to-pink-50/50',
  gray: 'border-slate-200/50 bg-gradient-to-br from-slate-50/40 to-gray-50/30 text-slate-700 group-hover:border-slate-300 group-hover:from-slate-50/60 group-hover:to-gray-50/50',
  cyan: 'border-cyan-200/50 bg-gradient-to-br from-cyan-50/40 to-sky-50/30 text-cyan-700 group-hover:border-cyan-300 group-hover:from-cyan-50/60 group-hover:to-sky-50/50',
  sky: 'border-sky-200/50 bg-gradient-to-br from-sky-50/40 to-blue-50/30 text-sky-700 group-hover:border-sky-300 group-hover:from-sky-50/60 group-hover:to-blue-50/50',
  rose: 'border-rose-200/50 bg-gradient-to-br from-rose-50/40 to-pink-50/30 text-rose-700 group-hover:border-rose-300 group-hover:from-rose-50/60 group-hover:to-pink-50/50',
  indigo: 'border-indigo-200/50 bg-gradient-to-br from-indigo-50/40 to-purple-50/30 text-indigo-700 group-hover:border-indigo-300 group-hover:from-indigo-50/60 group-hover:to-purple-50/50',
}

const iconBgStyles = {
  amber: 'bg-gradient-to-br from-amber-100 to-orange-100 text-amber-600 group-hover:from-amber-200 group-hover:to-orange-200',
  blue: 'bg-gradient-to-br from-sky-100 to-blue-100 text-sky-600 group-hover:from-sky-200 group-hover:to-blue-200',
  green: 'bg-gradient-to-br from-emerald-100 to-teal-100 text-emerald-600 group-hover:from-emerald-200 group-hover:to-teal-200',
  teal: 'bg-gradient-to-br from-teal-100 to-cyan-100 text-teal-600 group-hover:from-teal-200 group-hover:to-cyan-200',
  orange: 'bg-gradient-to-br from-orange-100 to-amber-100 text-orange-600 group-hover:from-orange-200 group-hover:to-amber-200',
  red: 'bg-gradient-to-br from-rose-100 to-pink-100 text-rose-600 group-hover:from-rose-200 group-hover:to-pink-200',
  gray: 'bg-gradient-to-br from-slate-100 to-gray-100 text-slate-600 group-hover:from-slate-200 group-hover:to-gray-200',
  cyan: 'bg-gradient-to-br from-cyan-100 to-sky-100 text-cyan-600 group-hover:from-cyan-200 group-hover:to-sky-200',
  sky: 'bg-gradient-to-br from-sky-100 to-blue-100 text-sky-600 group-hover:from-sky-200 group-hover:to-blue-200',
  rose: 'bg-gradient-to-br from-rose-100 to-pink-100 text-rose-600 group-hover:from-rose-200 group-hover:to-pink-200',
  indigo: 'bg-gradient-to-br from-indigo-100 to-purple-100 text-indigo-600 group-hover:from-indigo-200 group-hover:to-purple-200',
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
      ? "bg-slate-100/60 text-slate-500 border-slate-200/40"
      : active
        ? "bg-gradient-to-r from-sky-100 to-blue-100 text-sky-700 border-sky-300 shadow-md shadow-sky-200/30"
        : (colorStyles[color] || colorStyles.sky) + " border-sky-200/40 shadow-sm"

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
            ? "bg-slate-100 text-slate-400"
            : active
              ? "bg-gradient-to-br from-sky-200 to-blue-200 text-sky-700"
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
              isDimmed ? "text-slate-600" : "text-slate-900"
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

  const silentColorStyle = 'border-slate-200/60 bg-slate-50/40 text-slate-500'
  const silentIconStyle = 'bg-slate-100/60 text-slate-400'

  if (dense) {
    return (
      <div className={cn(
        'group flex items-center gap-3 rounded-2xl border px-3 py-2 shadow-sm backdrop-blur-sm transition-all duration-200 hover:shadow-md',
        isDimmed ? silentColorStyle : (colorStyles[color] || colorStyles.sky) + ' bg-white/80',
        className
      )}>
        <div className={cn('flex size-8 items-center justify-center rounded-xl shadow-sm transition-all duration-200 group-hover:scale-110', isDimmed ? silentIconStyle : (iconBgStyles[color] || iconBgStyles.sky))}>
          <Icon className="size-4" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-[10px] font-black uppercase text-slate-600">{label}</p>
          <p className={cn("truncate text-[14px] font-mono font-black tabular-nums transition-all duration-200", isDimmed ? "text-slate-600" : "text-slate-900")}>{value}</p>
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
        <p className="truncate text-[11px] font-black uppercase mb-1 text-slate-600">{label}</p>
        <div className="flex items-baseline gap-2">
          <p className={cn("truncate text-[24px] font-mono font-black leading-none transition-all duration-200", isDimmed ? "text-slate-600" : "text-slate-900")}>{value}</p>
          {unit && <span className="text-xs font-bold uppercase text-slate-500 transition-all duration-200">{unit}</span>}
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
