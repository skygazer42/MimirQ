'use client'

import { RouteError } from '@/components/route-error'

export default function DatasetDetailError({
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
      title="数据集加载失败"
      message="无法加载数据集详情，请重试或返回数据集列表。"
      href="/datasets"
      hrefLabel="返回列表"
    />
  )
}
