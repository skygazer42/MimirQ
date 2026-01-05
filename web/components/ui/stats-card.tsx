'use client'

import { cn } from '@/lib/utils'
import { LucideIcon } from 'lucide-react'

interface StatCardProps {
  icon: LucideIcon
  label: string
  value: string | number
  subValue?: string
  color?: 'blue' | 'green' | 'purple' | 'orange' | 'red' | 'gray' | 'indigo'
  className?: string
}

const colorStyles = {
  blue: 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 border-blue-100 dark:border-blue-800',
  green: 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400 border-emerald-100 dark:border-emerald-800',
  purple: 'bg-purple-50 dark:bg-purple-900/20 text-purple-600 dark:text-purple-400 border-purple-100 dark:border-purple-800',
  orange: 'bg-orange-50 dark:bg-orange-900/20 text-orange-600 dark:text-orange-400 border-orange-100 dark:border-orange-800',
  red: 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 border-red-100 dark:border-red-800',
  gray: 'bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-100 dark:border-slate-700',
  indigo: 'bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400 border-indigo-100 dark:border-indigo-800',
}

const iconBgStyles = {
  blue: 'bg-blue-100 dark:bg-blue-800',
  green: 'bg-emerald-100 dark:bg-emerald-800',
  purple: 'bg-purple-100 dark:bg-purple-800',
  orange: 'bg-orange-100 dark:bg-orange-800',
  red: 'bg-red-100 dark:bg-red-800',
  gray: 'bg-slate-100 dark:bg-slate-700',
  indigo: 'bg-indigo-100 dark:bg-indigo-800',
}

export function StatCard({
  icon: Icon,
  label,
  value,
  subValue,
  color = 'indigo',
  className,
}: StatCardProps) {
  return (
    <div
      className={cn(
        'flex items-center gap-3 px-4 py-3 rounded-xl border transition-all hover:shadow-md',
        colorStyles[color as keyof typeof colorStyles] || colorStyles.indigo,
        className
      )}
    >
      <div className={cn('p-2 rounded-lg flex-shrink-0', iconBgStyles[color as keyof typeof iconBgStyles] || iconBgStyles.indigo)}>
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
