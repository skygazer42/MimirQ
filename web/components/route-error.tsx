'use client'

import { useEffect } from 'react'
import Link from 'next/link'
import { AlertTriangle } from 'lucide-react'

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
  title = '页面加载失败',
  message = '发生了一个临时错误，请重试或返回首页继续操作。',
  href = '/',
  hrefLabel = '返回首页',
}: RouteErrorProps) {
  const requestId = extractRequestIdFromError(error)

  useEffect(() => {
    captureApiError(error, message, { tags: { boundary: 'route-error' } })
  }, [error, message])

  return (
    <Card className="w-full max-w-lg rounded-3xl shadow-strong">
      <CardContent className="p-8 text-center">
        <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-warning/10 text-warning">
          <AlertTriangle className="h-6 w-6" />
        </div>
        <h1 className="text-xl font-semibold text-foreground">{title}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{message}</p>
        <div className="mt-6 flex items-center justify-center gap-3">
          <Button onClick={() => reset()}>重试</Button>
          <Button variant="outline" asChild>
            <Link href={href}>{hrefLabel}</Link>
          </Button>
        </div>
        <div className="mt-4 space-y-1 text-xs font-mono text-muted-foreground">
          {requestId ? <p>请求 ID：request_id={requestId}</p> : null}
          {error?.digest ? <p>错误 ID：{error.digest}</p> : null}
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
