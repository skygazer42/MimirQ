import type { ReactNode } from 'react'
import { BrandLogo } from '@/components/brand-logo'
import { cn } from '@/lib/utils'

export const pageStatusActionClass = 'h-11 gap-2 rounded-md px-4 text-[13px] shadow-none sm:h-9'

type PageStatusProps = Readonly<{
  title: string
  description: ReactNode
  icon: ReactNode
  actions: ReactNode
  metadata?: ReactNode
  showBrand?: boolean
  className?: string
}>

export function PageStatus({ title, description, icon, actions, metadata, showBrand = false, className }: PageStatusProps) {
  return <section aria-label={title} data-page-status className={cn('flex min-h-0 w-full min-w-0 flex-1 flex-col items-center overflow-y-auto bg-background px-6 py-12 font-sans text-foreground sm:px-10', className)}>
    <div className="my-auto w-full max-w-[520px] shrink-0">
      {showBrand ? <BrandLogo decorative className="mb-10 w-[112px]" /> : null}
      <div aria-hidden="true" className="mb-5 text-muted-foreground [&>svg]:size-7">{icon}</div>
      <h1 className="m-0 text-[24px] font-semibold leading-[34px] tracking-normal">{title}</h1>
      <div className="mt-3 text-[14px] leading-[26px] text-muted-foreground">{description}</div>
      <div className="mt-6 flex flex-wrap items-center gap-2.5">{actions}</div>
      {metadata ? <div className="mt-7 border-t border-border pt-4 text-[12px] leading-[22px] text-muted-foreground">{metadata}</div> : null}
    </div>
  </section>
}
