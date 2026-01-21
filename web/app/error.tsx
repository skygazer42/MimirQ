'use client'

import { useEffect } from 'react'
import Link from 'next/link'
import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error(error)
  }, [error])

  return (
    <main id="main-content" tabIndex={-1} className="flex min-h-screen items-center justify-center bg-background px-6 py-10">
      <Card className="w-full max-w-lg rounded-3xl shadow-strong">
        <CardContent className="p-8 text-center">
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-500/10 text-amber-700 dark:text-amber-300">
          <AlertTriangle className="h-6 w-6" />
        </div>
          <h1 className="text-xl font-semibold text-foreground">页面加载失败</h1>
          <p className="mt-2 text-sm text-muted-foreground">
          发生了一个临时错误，请重试或返回首页继续操作。
        </p>
        <div className="mt-6 flex items-center justify-center gap-3">
          <Button onClick={() => reset()}>重试</Button>
          <Button variant="outline" asChild>
            <Link href="/">返回首页</Link>
          </Button>
        </div>
        {error?.digest && (
          <p className="mt-4 text-xs text-muted-foreground font-mono">错误 ID：{error.digest}</p>
        )}
        </CardContent>
      </Card>
    </main>
  )
}
