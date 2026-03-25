'use client'

import { ChunkStrategyProvider } from '@/contexts/chunk-strategy-context'
import { ParserBackendProvider } from '@/contexts/parser-backend-context'
import { PipelineCapabilitiesProvider } from '@/contexts/pipeline-capabilities-context'
import { PipelineOptionsProvider } from '@/contexts/pipeline-options-context'

export function PipelineProviders({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <PipelineCapabilitiesProvider>
      <ParserBackendProvider>
        <ChunkStrategyProvider>
          <PipelineOptionsProvider>{children}</PipelineOptionsProvider>
        </ChunkStrategyProvider>
      </ParserBackendProvider>
    </PipelineCapabilitiesProvider>
  )
}
