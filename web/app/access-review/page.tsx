'use client'

import { useEffect } from 'react'

import { useRouter } from '@/i18n/navigation'

export default function AccessReviewPage() {
  const router = useRouter()

  useEffect(() => {
    router.replace('/audit')
  }, [router])

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 text-sm font-medium text-slate-500">
      正在打开审计日志...
    </main>
  )
}
