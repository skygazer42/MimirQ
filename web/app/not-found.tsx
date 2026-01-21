import Link from 'next/link'
import { Compass } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

export default function NotFound() {
  return (
    <main id="main-content" tabIndex={-1} className="flex min-h-screen items-center justify-center bg-background px-6 py-10">
      <Card className="w-full max-w-lg rounded-3xl shadow-strong">
        <CardContent className="p-8 text-center">
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-sky-500/10 text-sky-700 dark:text-sky-300">
          <Compass className="h-6 w-6" />
        </div>
          <h1 className="text-xl font-semibold text-foreground">页面不存在</h1>
          <p className="mt-2 text-sm text-muted-foreground">
          你访问的地址可能已被移除或暂时不可用。
        </p>
        <div className="mt-6 flex items-center justify-center gap-3">
          <Button asChild>
            <Link href="/">返回首页</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href="/knowledge">前往知识库</Link>
          </Button>
        </div>
        </CardContent>
      </Card>
    </main>
  )
}
