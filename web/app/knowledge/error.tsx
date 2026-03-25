'use client'

import { RouteError } from '@/components/route-error'

export default function KnowledgeError({
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
      title="知识库加载失败"
      message="无法加载知识库内容，请重试或返回首页。"
    />
  )
}
