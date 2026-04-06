'use client'

import { usePathname } from 'next/navigation'

import { PageTransition } from "@/components/page-transition"
import { PipelineProviders } from '@/components/providers/pipeline-providers'

const PIPELINE_ROUTE_PREFIXES = [
  '/datasets',
  '/knowledge',
  '/parsing',
  '/chunk-preview',
  '/settings',
  '/data-governance',
]

function needsPipelineProviders(pathname: string): boolean {
  return PIPELINE_ROUTE_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))
}

export default function Template({ children }: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname() || ''
  const content = <PageTransition>{children}</PageTransition>

  if (!needsPipelineProviders(pathname)) {
    return content
  }

  return <PipelineProviders>{content}</PipelineProviders>
}
