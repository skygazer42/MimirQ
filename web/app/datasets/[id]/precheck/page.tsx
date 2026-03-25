'use client'

import dynamic from 'next/dynamic'

const DatasetPrecheckPageClient = dynamic(() => import('./page-client'), {
  ssr: false,
  loading: () => <div className="min-h-dvh bg-background" />,
})

export default function DatasetPrecheckPage() {
  return <DatasetPrecheckPageClient />
}
