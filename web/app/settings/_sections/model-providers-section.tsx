'use client'

import { ModelProviderCard } from '@/components/model-provider-card'
import type { ModelProvider, ProviderCategory } from '@/types/models'
import type { PlatformIcon } from '@/components/icons'
import { Cpu, Layers, Server } from '@/components/icons'
import { settingsTextTokens } from '@/components/ui/system-page-tokens'

const CATEGORY_INFO: Record<ProviderCategory, { title: string; description: string; icon: PlatformIcon }> = {
  model: {
    title: '语言模型',
    description: '用于对话和文本生成的大语言模型',
    icon: Server,
  },
  embedding: {
    title: '嵌入模型',
    description: '将文档和问题转换为检索向量。更换模型后，已有文档需重新入库。',
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
      <div className="space-y-7">
        {(['model', 'embedding', 'reranker'] as ProviderCategory[]).map((category) => {
          const info = CATEGORY_INFO[category]
          const InfoIcon = info.icon

          return (
            <div
              key={category}
              className="min-w-0"
            >
              <div className="mb-1 flex items-start gap-2">
                <div className="mt-1 shrink-0">
                  <InfoIcon className="h-4 w-4 text-muted-foreground" />
                </div>
                <div>
                  <h3 className="text-sm font-medium leading-6 text-foreground">{info.title}</h3>
                  <p className={settingsTextTokens.helpText}>{info.description}</p>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-x-8 xl:grid-cols-2">
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
