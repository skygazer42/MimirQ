'use client'

import { RouteError } from '@/components/route-error'

export default function GraphError({
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
      title="图谱加载失败"
      message="无法加载知识图谱，请重试或返回首页。"
    />
  )
}
