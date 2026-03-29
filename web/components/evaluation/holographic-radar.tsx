'use client'

import dynamic from 'next/dynamic'
import { PageLoading } from '@/components/ui/page-loading'

type HolographicRadarProps = Readonly<{
  data: Array<{ subject: string; score: number; fullMark: number }>
  className?: string
}>

const HolographicRadarClient = dynamic(
  () => import('./holographic-radar-client').then((mod) => mod.HolographicRadar),
  {
    ssr: false,
    loading: () => (
      <div className="aspect-square w-full rounded-2xl border border-border/60 bg-card/40 px-6 py-5 shadow-soft">
        <PageLoading
          message="正在加载评测雷达"
          srMessage="Loading holographic radar"
          className="h-full min-h-full rounded-xl"
        />
      </div>
    ),
  }
)

export function HolographicRadar(props: HolographicRadarProps) {
  return <HolographicRadarClient {...props} />
}
