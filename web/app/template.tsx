'use client'

import type { ReactNode } from 'react'
import { usePathname } from 'next/navigation'

import { PageTransition } from '@/components/page-transition'
import { PipelineProviders } from '@/components/providers/pipeline-providers'
import { needsPipelineProvidersForPathname } from '@/lib/pipeline-route-scope'

export default function Template({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname() || ''
  const content = <PageTransition>{children}</PageTransition>

  if (!needsPipelineProvidersForPathname(pathname)) {
    return content
  }

  return <PipelineProviders>{content}</PipelineProviders>
}
