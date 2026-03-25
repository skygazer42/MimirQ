'use client'

import { ModelProviderCard } from '@/components/model-provider-card'
import type { ModelProvider, ProviderCategory } from '@/types/models'
import type { LucideIcon } from 'lucide-react'
import { Cpu, Layers, Lightbulb, Server } from 'lucide-react'

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
      <div className="mb-6 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <Server className="h-5 w-5 text-primary" />
          模型服务商
        </h2>
        <div className="flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
          <Lightbulb className="h-3 w-3" />
          <span>点击卡片配置 API Key</span>
        </div>
      </div>

      <div className="space-y-8">
        {(['model', 'embedding', 'reranker'] as ProviderCategory[]).map((category) => {
          const info = CATEGORY_INFO[category]
          const InfoIcon = info.icon

          return (
            <div
              key={category}
              className="rounded-2xl border border-border bg-card p-6 shadow-sm transition-shadow duration-200 hover:shadow-md motion-reduce:transition-none"
            >
              <div className="mb-6 flex items-start gap-4">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border bg-muted/50">
                  <InfoIcon className="h-5 w-5 text-muted-foreground" />
                </div>
                <div>
                  <h3 className="text-base font-medium text-foreground">{info.title}</h3>
                  <p className="mt-0.5 text-sm text-muted-foreground">{info.description}</p>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
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
