'use client'

import { useEffect } from 'react'
import { ConnectionLost } from '@/components/icons'
import Link from 'next/link'
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

function retryRouteAfterBoundaryError(reset: () => void) {
  reset()
  if (globalThis.window === undefined) return
  globalThis.window.location.reload()
}

function RouteErrorScene({
  error,
  reset,
  title,
  message,
  href = '/',
  hrefLabel,
}: RouteErrorProps) {
  const t = useTranslations('RouteBoundaries')
  const requestId = extractRequestIdFromError(error)
  const resolvedTitle = title ?? t("error.title")
  const resolvedMessage = message ?? t("error.message")
  const resolvedHrefLabel = hrefLabel ?? t("error.home")

  useEffect(() => {
    if (reloadOnceForStaleChunk(error)) return
    captureApiError(error, resolvedMessage, { tags: { boundary: 'route-error' } })
  }, [error, resolvedMessage])

  return <PageStatus
    title={resolvedTitle}
    description={resolvedMessage}
    icon={<ConnectionLost />}
    showBrand
    className="min-h-dvh"
    actions={<><Button className={pageStatusActionClass} onClick={() => retryRouteAfterBoundaryError(reset)}>{t('error.retry')}</Button><Button variant="outline" className={pageStatusActionClass} asChild><Link href={href}>{resolvedHrefLabel}</Link></Button></>}
    metadata={requestId || error.digest ? <div className="space-y-1 break-all font-mono">{requestId ? <p>{t('error.requestId', { requestId })}</p> : null}{error.digest ? <p>{t('error.errorId', { errorId: error.digest })}</p> : null}</div> : undefined}
  />
}

export function RouteError(props: RouteErrorProps) {
  if (props.fullScreen) {
    return (
      <FullScreenFrame
        showBackground={false}
        className="bg-background"
        mainClassName="p-0"
      >
        <RouteErrorScene {...props} fullScreen />
      </FullScreenFrame>
    )
  }

  return (
    <div className="flex min-h-dvh w-full flex-1 items-stretch justify-center bg-background">
      <RouteErrorScene {...props} />
    </div>
  )
}
