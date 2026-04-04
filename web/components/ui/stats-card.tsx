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
}: Readonly<StatCardProps>) {
  return (
    <div
      className={cn(
        'flex items-center gap-3 px-4 py-3 rounded-xl border transition-colors duration-200 motion-reduce:transition-none hover:bg-opacity-15',
        colorStyles[color] || colorStyles.sky,
        className
      )}
    >
      <div className={cn('p-2 rounded-xl flex-shrink-0', iconBgStyles[color] || iconBgStyles.sky)}>
        <Icon className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs text-muted-foreground truncate font-medium">{label}</p>
        <p className="text-xl font-bold leading-tight truncate tabular-nums">{value}</p>
        {subValue && (
          <p className="text-xs text-muted-foreground/80 truncate">{subValue}</p>
        )}
      </div>
    </div>
  )
}

interface StatsGridProps {
  children: React.ReactNode
  className?: string
}

export function StatsGrid({ children, className }: Readonly<StatsGridProps>) {
  return (
    <div
      className={cn(
        'grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4',
        className
      )}
    >
      {children}
    </div>
  )
}
