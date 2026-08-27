'use client'

import { useEffect } from 'react'

import { useRouter } from '@/i18n/navigation'

export default function AccessReviewPage() {
  const router = useRouter()

  useEffect(() => {
    router.replace('/audit')
  }, [router])

  return (
    <main className="flex min-h-screen items-center justify-center bg-background text-sm font-medium text-muted-foreground">
      正在打开审计日志...
    </main>
  )
}
