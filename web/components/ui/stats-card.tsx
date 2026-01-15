'use client'

import { cn } from '@/lib/utils'
import { LucideIcon } from 'lucide-react'

interface StatCardProps {
  icon: LucideIcon
  label: string
  value: string | number
  subValue?: string
  color?: 'amber' | 'blue' | 'green' | 'teal' | 'orange' | 'red' | 'gray' | 'cyan' | 'sky' | 'rose'
  className?: string
}

const colorStyles = {
  amber: 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 border-amber-100 dark:border-amber-800',
  blue: 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 border-blue-100 dark:border-blue-800',
  green: 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400 border-emerald-100 dark:border-emerald-800',
  teal: 'bg-teal-50 dark:bg-teal-900/20 text-teal-600 dark:text-teal-400 border-teal-100 dark:border-teal-800',
  orange: 'bg-orange-50 dark:bg-orange-900/20 text-orange-600 dark:text-orange-400 border-orange-100 dark:border-orange-800',
  red: 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 border-red-100 dark:border-red-800',
  gray: 'bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-100 dark:border-slate-700',
  cyan: 'bg-cyan-50 dark:bg-cyan-900/20 text-cyan-600 dark:text-cyan-400 border-cyan-100 dark:border-cyan-800',
  sky: 'bg-sky-50 dark:bg-sky-900/20 text-sky-600 dark:text-sky-400 border-sky-100 dark:border-sky-800',
  rose: 'bg-rose-50 dark:bg-rose-900/20 text-rose-600 dark:text-rose-400 border-rose-100 dark:border-rose-800',
}

const iconBgStyles = {
  amber: 'bg-amber-100 dark:bg-amber-800',
  blue: 'bg-blue-100 dark:bg-blue-800',
  green: 'bg-emerald-100 dark:bg-emerald-800',
  teal: 'bg-teal-100 dark:bg-teal-800',
  orange: 'bg-orange-100 dark:bg-orange-800',
  red: 'bg-red-100 dark:bg-red-800',
  gray: 'bg-slate-100 dark:bg-slate-700',
  cyan: 'bg-cyan-100 dark:bg-cyan-800',
  sky: 'bg-sky-100 dark:bg-sky-800',
  rose: 'bg-rose-100 dark:bg-rose-800',
}

export function StatCard({
  icon: Icon,
  label,
  value,
  subValue,
  color = 'sky',
  className,
}: StatCardProps) {
  return (
    <div
      className={cn(
        'flex items-center gap-3 px-4 py-3 rounded-xl border transition-all hover:shadow-md',
        colorStyles[color as keyof typeof colorStyles] || colorStyles.sky,
        className
      )}
    >
      <div className={cn('p-2 rounded-lg flex-shrink-0', iconBgStyles[color as keyof typeof iconBgStyles] || iconBgStyles.sky)}>
        <Icon className="w-4 h-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs text-slate-500 dark:text-slate-400 truncate font-medium">{label}</p>
        <p className="text-lg font-bold leading-tight truncate">{value}</p>
        {subValue && (
          <p className="text-xs text-slate-400 dark:text-slate-500 truncate">{subValue}</p>
        )}
      </div>
    </div>
  )
}

interface StatsGridProps {
  children: React.ReactNode
  className?: string
}

export function StatsGrid({ children, className }: StatsGridProps) {
  return (
    <div
      className={cn(
        'grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4',
        className
      )}
    >
      {children}
    </div>
  )
}
