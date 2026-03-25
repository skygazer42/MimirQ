'use client'

import dynamic from 'next/dynamic'

type QuerysetHealthTabProps = Readonly<{ embedded?: boolean }>

const QuerysetHealthTabClient = dynamic(
  () => import('./queryset-health-tab-client').then((mod) => mod.QuerysetHealthTab),
  {
    ssr: false,
    loading: () => <div className="h-80 rounded-2xl border border-border/60 bg-muted/20 animate-pulse" />,
  }
)

export function QuerysetHealthTab(props: QuerysetHealthTabProps) {
  return <QuerysetHealthTabClient {...props} />
}
