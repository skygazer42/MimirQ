'use client'

import { useEffect } from 'react'
import Link from 'next/link'
import { AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'

export default function DatasetDetailError({
  error,
  reset,
}: Readonly<{
  error: Error & { digest?: string }
  reset: () => void
}>) {
  useEffect(() => {
    console.error(error)
  }, [error])

  return (
    <div className="flex-1 flex items-center justify-center p-6">
      <div className="max-w-md text-center space-y-4">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-destructive/10 text-destructive">
          <AlertCircle className="h-6 w-6" />
        </div>
        <h2 className="text-lg font-semibold text-foreground">数据集加载失败</h2>
        <p className="text-sm text-muted-foreground">
          无法加载数据集详情，请重试或返回数据集列表。
        </p>
        <div className="flex items-center justify-center gap-3">
          <Button onClick={() => reset()}>重试</Button>
          <Button variant="outline" asChild>
            <Link href="/datasets">返回列表</Link>
          </Button>
        </div>
        {error?.digest && (
          <p className="text-xs font-mono text-muted-foreground">错误 ID：{error.digest}</p>
        )}
      </div>
    </div>
  )
}
