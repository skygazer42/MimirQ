'use client'

import { usePathname } from 'next/navigation'
import type { ReactNode } from 'react'

import { PageTransition } from '@/components/page-transition'
import { PipelineProviders } from '@/components/providers/pipeline-providers'
import { routing } from '@/i18n/routing'

const PIPELINE_ROUTE_SEGMENTS = ['datasets', 'knowledge', 'parsing', 'chunk-preview', 'settings', 'data-governance']

export default function Template({ children }: Readonly<{ children: ReactNode }>) {
  // The global error route prerenders this template outside the locale provider.
  const [, firstSegment, secondSegment] = usePathname().split('/')
  const routeSegment = routing.locales.some((locale) => locale === firstSegment) ? secondSegment : firstSegment
  const content = <PageTransition>{children}</PageTransition>

  if (!PIPELINE_ROUTE_SEGMENTS.includes(routeSegment)) {
    return content
  }

  return <PipelineProviders>{content}</PipelineProviders>
}
