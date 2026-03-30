'use client'

import { useEffect } from 'react'
import Link from 'next/link'
import { AlertTriangle } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { FullScreenFrame } from '@/components/full-screen-frame'
import { captureApiError, extractRequestIdFromError } from '@/lib/api-errors'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

type RouteErrorProps = Readonly<{
  error: Error & { digest?: string }
  reset: () => void
  title?: string
  message?: string
  href?: string
  hrefLabel?: string
  fullScreen?: boolean
}>

function RouteErrorCard({
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
    captureApiError(error, resolvedMessage, { tags: { boundary: 'route-error' } })
  }, [error, resolvedMessage])

  return (
    <Card className="w-full max-w-lg rounded-3xl shadow-strong">
      <CardContent className="p-8 text-center">
        <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-warning/10 text-warning">
          <AlertTriangle className="h-6 w-6" />
        </div>
        <h1 className="text-xl font-semibold text-foreground">{resolvedTitle}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{resolvedMessage}</p>
        <div className="mt-6 flex items-center justify-center gap-3">
          <Button onClick={() => reset()}>{t("error.retry")}</Button>
          <Button variant="outline" asChild>
            <Link href={href}>{resolvedHrefLabel}</Link>
          </Button>
        </div>
        <div className="mt-4 space-y-1 text-xs font-mono text-muted-foreground">
          {requestId ? <p>{t("error.requestId", { requestId })}</p> : null}
          {error?.digest ? <p>{t("error.errorId", { errorId: error.digest })}</p> : null}
        </div>
      </CardContent>
    </Card>
  )
}

export function RouteError(props: RouteErrorProps) {
  if (props.fullScreen) {
    return (
      <FullScreenFrame>
        <RouteErrorCard {...props} />
      </FullScreenFrame>
    )
  }

  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <RouteErrorCard {...props} />
    </div>
  )
}
