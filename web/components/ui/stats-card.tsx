'use client'

import { cn } from '@/lib/utils'
import { LucideIcon } from 'lucide-react'

interface StatCardProps {
  icon: LucideIcon
  label: string
  value: string | number
  subValue?: string
  color?: 'amber' | 'blue' | 'green' | 'teal' | 'orange' | 'red' | 'gray' | 'cyan' | 'sky' | 'rose' | 'indigo'
  className?: string
  dense?: boolean
}

const colorStyles = {
  amber: 'bg-warning/10 text-warning border-warning/20',
  blue: 'bg-info/10 text-info border-info/20',
  green: 'bg-success/10 text-success border-success/20',
  teal: 'bg-teal/10 text-teal border-teal/20',
  orange: 'bg-orange/10 text-orange border-orange/20',
  red: 'bg-destructive/10 text-destructive border-destructive/20',
  gray: 'bg-muted text-muted-foreground border-border',
  cyan: 'bg-primary/10 text-primary border-primary/20',
  sky: 'bg-info/10 text-info border-info/20',
  rose: 'bg-rose/10 text-rose border-rose/20',
  indigo: 'bg-indigo/10 text-indigo border-indigo/20',
}

const iconBgStyles = {
  amber: 'bg-warning/20',
  blue: 'bg-info/20',
  green: 'bg-success/20',
  teal: 'bg-teal/20',
  orange: 'bg-orange/20',
  red: 'bg-destructive/20',
  gray: 'bg-muted',
  cyan: 'bg-primary/20',
  sky: 'bg-info/20',
  rose: 'bg-rose/20',
  indigo: 'bg-indigo/20',
}

export function StatCard({
  icon: Icon,
  label,
  value,
  subValue,
  color = 'sky',
  className,
  dense = false,
}: Readonly<StatCardProps>) {
  return (
    <div
      className={cn(
        dense
          ? 'flex items-center gap-2 rounded-lg border px-3 py-2 transition-colors duration-200 motion-reduce:transition-none hover:bg-opacity-15'
          : 'flex items-center gap-3 rounded-xl border px-4 py-3 transition-colors duration-200 motion-reduce:transition-none hover:bg-opacity-15',
        colorStyles[color] || colorStyles.sky,
        className
      )}
    >
      <div className={cn(dense ? 'rounded-lg p-1.5' : 'rounded-xl p-2', 'flex-shrink-0', iconBgStyles[color] || iconBgStyles.sky)}>
        <Icon className={dense ? 'size-3.5' : 'size-4'} />
      </div>
      <div className="min-w-0 flex-1">
        <p className={cn(dense ? 'text-[10px] font-semibold uppercase tracking-[0.08em]' : 'text-xs font-medium', 'truncate text-muted-foreground')}>
          {label}
        </p>
        <p className={cn(dense ? 'text-base font-semibold' : 'text-xl font-bold', 'truncate leading-tight tabular-nums')}>{value}</p>
        {subValue && (
          <p className={cn(dense ? 'text-[10px]' : 'text-xs', 'truncate text-muted-foreground/80')}>{subValue}</p>
        )}
      </div>
    </div>
  )
}

interface StatsGridProps {
  children: React.ReactNode
  className?: string
  dense?: boolean
}

export function StatsGrid({ children, className, dense = false }: Readonly<StatsGridProps>) {
  return (
    <div
      className={cn(
        dense
          ? 'grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6'
          : 'grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5',
        className
      )}
    >
      {children}
    </div>
  )
}
