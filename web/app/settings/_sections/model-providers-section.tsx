'use client'

import { ModelProviderCard } from '@/components/model-provider-card'
import type { ModelProvider, ProviderCategory } from '@/types/models'
import type { LucideIcon } from 'lucide-react'
import { Cpu, Layers, Server } from 'lucide-react'
import { cn } from '@/lib/utils'
import { systemPageTokens, systemWorkbenchTokens } from '@/components/ui/system-page-tokens'

const CATEGORY_INFO: Record<ProviderCategory, { title: string; description: string; icon: LucideIcon }> = {
  model: {
    title: '语言模型',
    description: '用于对话和文本生成的大语言模型',
    icon: Server,
  },
  embedding: {
    title: '向量模型',
    description: '用于文档语义理解和检索',
    icon: Cpu,
  },
  reranker: {
    title: '重排序模型',
    description: '优化检索结果的相关性排序',
    icon: Layers,
  },
}

type ModelProvidersSectionProps = {
  groupedProviders: Record<ProviderCategory, ModelProvider[]>
  onConfigure: (provider: ModelProvider) => void
}

export function ModelProvidersSection({
  groupedProviders,
  onConfigure,
}: Readonly<ModelProvidersSectionProps>) {
  return (
    <section>
      <div className="space-y-4">
        {(['model', 'embedding', 'reranker'] as ProviderCategory[]).map((category) => {
          const info = CATEGORY_INFO[category]
          const InfoIcon = info.icon

          return (
            <div
              key={category}
              className={cn(systemWorkbenchTokens.panel, 'border-info/15 bg-info/[0.025] p-3.5')}
            >
              <div className="mb-3 flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border/70 bg-muted/35">
                  <InfoIcon className="h-4 w-4 text-muted-foreground" />
                </div>
                <div>
                  <h3 className="text-[13px] font-semibold text-foreground">{info.title}</h3>
                  <p className={systemPageTokens.subtle}>{info.description}</p>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                {groupedProviders[category].map((provider) => (
                  <ModelProviderCard
                    key={provider.id}
                    provider={provider}
                    onConfigure={onConfigure}
                  />
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
