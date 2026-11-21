'use client'

import { useTranslations } from 'next-intl'
import { cn } from '@/lib/utils'

type PageLoadingProps = {
  readonly message?: string
  /**
   * 可覆盖可见文字的屏幕阅读器提示
   */
  readonly srMessage?: string
  /**
   * 额外的容器样式
   */
  readonly className?: string
}

export function PageLoading({ message, srMessage, className }: PageLoadingProps) {
  const t = useTranslations('CommonUi')
  const resolvedMessage = message ?? t('pageLoading.message')

  return (
    <div role="status" aria-live="polite" className={cn('flex-1 flex items-center justify-center', className)}>
      <div className="flex items-center gap-3 text-muted-foreground font-medium">
        <div
          className="h-6 w-6 animate-spin motion-reduce:animate-none rounded-full border-2 border-border border-t-primary"
          aria-hidden="true"
        />
        <span aria-hidden={srMessage !== undefined}>{resolvedMessage}</span>
        {srMessage === undefined ? null : <span className="sr-only">{srMessage}</span>}
      </div>
    </div>
  )
}
