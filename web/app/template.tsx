'use client'

import type { ReactNode } from 'react'

import { PageTransition } from '@/components/page-transition'
import { PipelineProviders } from '@/components/providers/pipeline-providers'
import { usePathname } from '@/i18n/navigation'

const PIPELINE_ROUTE_PREFIXES = [
  '/datasets',
  '/knowledge',
  '/parsing',
  '/chunk-preview',
  '/settings',
  '/data-governance',
] as const

export default function Template({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname()
  const content = <PageTransition>{children}</PageTransition>
  const needsPipelineProviders = PIPELINE_ROUTE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  )

  if (!needsPipelineProviders) {
    return content
  }

  return <PipelineProviders>{content}</PipelineProviders>
}
