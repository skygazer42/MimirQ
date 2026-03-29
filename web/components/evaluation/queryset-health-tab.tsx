'use client'

import dynamic from 'next/dynamic'

import { Panel } from '@/components/ui/panel'
import { Skeleton } from '@/components/ui/skeleton'

type QuerysetHealthTabProps = Readonly<{ embedded?: boolean }>

const QuerysetHealthTabClient = dynamic(
  () => import('./queryset-health-tab-client').then((mod) => mod.QuerysetHealthTab),
  {
    ssr: false,
    loading: () => (
      <Panel className="h-80 rounded-2xl border border-border/60 bg-background/70 shadow-soft" padding="lg">
        <div className="flex flex-col h-full items-start justify-between gap-6">
          <div>
            <Skeleton className="h-5 w-32" />
            <Skeleton className="mt-2 h-4 w-48" />
          </div>
          <div className="self-stretch space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-3/5" />
          </div>
          <div className="self-end flex items-center gap-3">
            <Skeleton className="h-9 w-20 rounded-full" />
            <Skeleton className="h-9 w-24 rounded-full" />
          </div>
        </div>
      </Panel>
    ),
  }
)

export function QuerysetHealthTab(props: QuerysetHealthTabProps) {
  return <QuerysetHealthTabClient {...props} />
}
