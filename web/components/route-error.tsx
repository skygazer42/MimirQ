'use client'

import { startTransition, useEffect } from 'react'
import { ConnectionLost } from '@/components/icons'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'

import { FullScreenFrame } from '@/components/full-screen-frame'
import { PageStatus, pageStatusActionClass } from '@/components/ui/page-status'
import { extractRequestIdFromError } from '@/lib/api-errors'
import { captureApiError } from '@/lib/api-error-reporting'
import { reloadOnceForStaleChunk } from '@/lib/stale-chunk-recovery'
import { Button } from '@/components/ui/button'

type RouteErrorProps = Readonly<{
  error: Error & { digest?: string }
  reset: () => void
  title?: string
  message?: string
  href?: string
  hrefLabel?: string
  fullScreen?: boolean
}>

export function RouteError({ error, reset, title, message, href = '/', hrefLabel, fullScreen }: RouteErrorProps) {
  const router = useRouter()
  const t = useTranslations('RouteBoundaries')
  const requestId = extractRequestIdFromError(error)
  const resolvedTitle = title ?? t('error.title')
  const resolvedHrefLabel = hrefLabel ?? t('error.home')

  useEffect(() => {
    if (reloadOnceForStaleChunk(error)) return
    captureApiError(error, message ?? resolvedTitle, { tags: { boundary: 'route-error' } })
  }, [error, message, resolvedTitle])

  const status = (
    <PageStatus
      title={resolvedTitle}
      description={message}
      icon={<ConnectionLost />}
      showBrand
      className="min-h-dvh"
      actions={
        <>
          <Button
            className={pageStatusActionClass}
            onClick={() => {
              startTransition(() => {
                router.refresh()
                reset()
              })
            }}
          >
            {t('error.retry')}
          </Button>
          <Button variant="outline" className={pageStatusActionClass} asChild>
            <Link href={href}>{resolvedHrefLabel}</Link>
          </Button>
        </>
      }
      metadata={
        requestId || error.digest ? (
          <div className="space-y-1 break-all font-mono">
            {requestId ? <p>{t('error.requestId', { requestId })}</p> : null}
            {error.digest ? <p>{t('error.errorId', { errorId: error.digest })}</p> : null}
          </div>
        ) : undefined
      }
    />
  )

  if (fullScreen) {
    return <FullScreenFrame mainClassName="p-0">{status}</FullScreenFrame>
  }

  return <div className="flex min-h-dvh w-full flex-1 items-stretch justify-center bg-background">{status}</div>
}
