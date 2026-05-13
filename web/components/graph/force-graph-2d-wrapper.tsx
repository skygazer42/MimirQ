'use client'

import dynamic from 'next/dynamic'
import type { MutableRefObject } from 'react'

import { Skeleton } from '@/components/ui/skeleton'

const ForceGraph2D = dynamic(() => import('react-force-graph-2d'), {
  ssr: false,
  loading: () => (
    <div className="h-full w-full rounded-xl border border-border/60 bg-card/40 p-4">
      <div className="grid h-full place-items-center">
        <div className="w-full max-w-sm space-y-3">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      </div>
    </div>
  ),
})

type ForceGraph2DWrapperProps = Readonly<
  {
    graphRef?: MutableRefObject<any>
  } & Record<string, unknown>
>

export default function ForceGraph2DWrapper({ graphRef, ...props }: ForceGraph2DWrapperProps) {
  return <ForceGraph2D ref={graphRef} {...props} />
}
