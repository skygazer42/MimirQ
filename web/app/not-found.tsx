import Link from 'next/link'
import { Compass } from 'lucide-react'
import { Button } from '@/components/ui/button'

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-6">
      <div className="w-full max-w-lg rounded-3xl border border-slate-200 bg-white p-8 text-center shadow-sm">
        <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-sky-50 text-sky-600">
          <Compass className="h-6 w-6" />
        </div>
        <h1 className="text-xl font-semibold text-slate-900">页面不存在</h1>
        <p className="mt-2 text-sm text-slate-500">
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
      </div>
    </div>
  )
}
