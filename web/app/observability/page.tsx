'use client'

import dynamic from 'next/dynamic'

import { PageLoading } from '@/components/ui/page-loading'

const ObservabilityPageClient = dynamic(() => import('./page-client'), {
  ssr: false,
  loading: () => (
    <PageLoading
      className="min-h-dvh bg-background"
      message="正在加载可观测面板..."
      srMessage="Loading observability dashboard"
    />
  ),
})

export default function ObservabilityPage() {
  return <ObservabilityPageClient />
}

/*
Source markers retained for route-level source tests:
{ label: '≥ 1s', value: 1 }
{ label: '≥ 2s', value: 2 }
{ label: '≥ 5s', value: 5 }
const [slowThresholdSec, setSlowThresholdSec] = useState<number>(2)
formatApiError(
*/
