'use client'

import dynamic from 'next/dynamic'

type HolographicRadarProps = Readonly<{
  data: Array<{ subject: string; score: number; fullMark: number }>
  className?: string
}>

const HolographicRadarClient = dynamic(
  () => import('./holographic-radar-client').then((mod) => mod.HolographicRadar),
  {
    ssr: false,
    loading: () => <div className="aspect-square w-full rounded-full bg-muted/20 animate-pulse" />,
  }
)

export function HolographicRadar(props: HolographicRadarProps) {
  return <HolographicRadarClient {...props} />
}
