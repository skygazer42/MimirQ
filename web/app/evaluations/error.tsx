'use client'

import { RouteError } from '@/components/route-error'

export default function EvaluationsError({
  error,
  reset,
}: Readonly<{
  error: Error & { digest?: string }
  reset: () => void
}>) {
  return (
    <RouteError
      error={error}
      reset={reset}
      title="评测页加载失败"
      message="无法加载评测数据，请重试或返回首页。"
    />
  )
}
