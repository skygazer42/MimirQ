/**
 * 设置页面 - 模型提供商配置
 */
'use client'

import { useState, useMemo } from 'react'
import { Navbar } from '@/components/navbar'
import { ModelProviderCard } from '@/components/model-provider-card'
import { ModelConfigDialog } from '@/components/model-config-dialog'
import { MODEL_PROVIDERS } from '@/types/models'
import type { ModelProvider, ProviderConfig, ProviderCategory } from '@/types/models'

const CATEGORY_INFO: Record<ProviderCategory, { title: string; description: string; icon: string }> = {
  model: {
    title: '语言模型',
    description: '用于对话和文本生成的大语言模型',
    icon: '💬',
  },
  embedding: {
    title: 'Embedding 向量模型',
    description: '将文本转换为向量表示，用于语义搜索',
    icon: '🔢',
  },
  reranker: {
    title: 'Reranker 重排序模型',
    description: '对检索结果进行重新排序，提升相关性',
    icon: '📊',
  },
}

export default function SettingsPage() {
  const [providers, setProviders] = useState<ModelProvider[]>(MODEL_PROVIDERS)
  const [selectedProvider, setSelectedProvider] = useState<ModelProvider | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  const handleConfigure = (provider: ModelProvider) => {
    setSelectedProvider(provider)
    setDialogOpen(true)
  }

  const handleSaveConfig = (providerId: string, config: ProviderConfig) => {
    setProviders((prev) =>
      prev.map((p) =>
        p.id === providerId
          ? { ...p, isConfigured: true, config }
          : p
      )
    )
  }

  // 按分类分组
  const groupedProviders = useMemo(() => {
    const groups: Record<ProviderCategory, ModelProvider[]> = {
      model: [],
      embedding: [],
      reranker: [],
    }
    providers.forEach((p) => {
      groups[p.category].push(p)
    })
    return groups
  }, [providers])

  const getConfiguredCount = (category: ProviderCategory) => {
    return groupedProviders[category].filter((p) => p.isConfigured).length
  }

  const totalConfigured = providers.filter((p) => p.isConfigured).length

  return (
    <div className="flex h-screen overflow-hidden bg-white">
      <Navbar />
      <main className="flex-1 overflow-y-auto p-8">
        <div className="max-w-7xl mx-auto">
          {/* 页面头部 */}
          <div className="mb-8">
            <h1 className="text-3xl font-bold text-gray-900 mb-2">模型配置</h1>
            <p className="text-gray-600">
              配置 AI 模型提供商以启用智能对话功能
            </p>
          </div>

          {/* 按分类展示 */}
          {(['model', 'embedding', 'reranker'] as ProviderCategory[]).map((category) => (
            <div key={category} className="mb-12">
              {/* 分类标题 */}
              <div className="flex items-center gap-3 mb-6">
                <span className="text-2xl">{CATEGORY_INFO[category].icon}</span>
                <div>
                  <h2 className="text-xl font-bold text-gray-900">
                    {CATEGORY_INFO[category].title}
                  </h2>
                  <p className="text-sm text-gray-500">
                    {CATEGORY_INFO[category].description}
                  </p>
                </div>
              </div>

              {/* 提供商网格 */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {groupedProviders[category].map((provider) => (
                  <ModelProviderCard
                    key={provider.id}
                    provider={provider}
                    onConfigure={handleConfigure}
                  />
                ))}
              </div>

              {/* 分割线 */}
              {category !== 'reranker' && (
                <div className="mt-10 border-b border-gray-200"></div>
              )}
            </div>
          ))}

          {/* 帮助提示 */}
          <div className="mt-8 bg-blue-50 border border-blue-200 rounded-lg p-6">
            <h3 className="text-lg font-semibold text-blue-900 mb-2">
              配置提示
            </h3>
            <ul className="space-y-2 text-sm text-blue-800">
              <li>• 点击任意卡片进行配置,输入对应的 API Key</li>
              <li>• 支持使用自定义 API Base URL (如代理服务)</li>
              <li>• 配置完成后可以测试连接确保可用性</li>
              <li>• 本地模型无需 API Key,开箱即用</li>
            </ul>
          </div>

          {/* 其他设置部分 */}
          <div className="mt-12">
            <h2 className="text-2xl font-bold text-gray-900 mb-6">系统设置</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* 数据库设置 */}
              <div className="bg-white border border-gray-200 rounded-lg p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                  数据库连接
                </h3>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      PostgreSQL URL
                    </label>
                    <input
                      type="text"
                      defaultValue="postgresql://postgres:postgres@localhost:5432/mimirq"
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
                      readOnly
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Milvus Host
                    </label>
                    <input
                      type="text"
                      defaultValue="localhost:19530"
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
                      readOnly
                    />
                  </div>
                  <p className="text-xs text-gray-500">
                    数据库配置通过环境变量管理
                  </p>
                </div>
              </div>

              {/* RAG 参数设置 */}
              <div className="bg-white border border-gray-200 rounded-lg p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                  检索参数
                </h3>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Top K
                    </label>
                    <input
                      type="number"
                      defaultValue={5}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                    <p className="text-xs text-gray-500 mt-1">
                      返回的最相关文档数量
                    </p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      相似度阈值
                    </label>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      max="1"
                      defaultValue={0.7}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                    <p className="text-xs text-gray-500 mt-1">
                      文档相关性过滤阈值 (0-1)
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* 配置对话框 */}
      <ModelConfigDialog
        provider={selectedProvider}
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSave={handleSaveConfig}
      />
    </div>
  )
}
