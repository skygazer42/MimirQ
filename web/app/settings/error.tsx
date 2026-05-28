'use client'

import { RouteError } from '@/components/route-error'

export default function SettingsError({
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
      title="设置页加载失败"
      message="无法加载系统设置，请重试或返回首页"
      fullScreen
    />
  )
}
