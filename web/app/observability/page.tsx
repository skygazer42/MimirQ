'use client'

import dynamic from 'next/dynamic'

const ObservabilityPageClient = dynamic(() => import('./page-client'), {
  ssr: false,
  loading: () => <div className="min-h-dvh bg-background" />,
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
