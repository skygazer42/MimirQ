import { cn } from '@/lib/utils'

type PageToolbarProps = {
  children: React.ReactNode
  className?: string
}

export function PageToolbar({ children, className }: Readonly<PageToolbarProps>) {
  return <div className={cn('flex flex-wrap items-center gap-3', className)}>{children}</div>
}
