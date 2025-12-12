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
import { Settings2, Database, Sliders, Lightbulb, Server, Cpu, Layers } from 'lucide-react'

const CATEGORY_INFO: Record<ProviderCategory, { title: string; description: string; icon: any }> = {
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

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50/50">
      <Navbar />
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-6xl mx-auto px-8 py-10">
          {/* 页面头部 */}
          <div className="flex items-center gap-4 mb-10">
            <div className="p-3 bg-white border border-gray-100 rounded-xl shadow-sm">
              <Settings2 className="h-6 w-6 text-gray-700" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 tracking-tight">设置与配置</h1>
              <p className="text-sm text-gray-500 mt-1">
                管理模型接入、系统参数及数据库连接
              </p>
            </div>
          </div>

          <div className="space-y-12">
            {/* 模型配置区域 */}
            <section>
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                  <Server className="h-5 w-5 text-blue-600" />
                  模型服务商
                </h2>
                <div className="flex items-center gap-2 px-3 py-1 bg-blue-50 text-blue-700 rounded-full text-xs font-medium border border-blue-100">
                  <Lightbulb className="h-3 w-3" />
                  <span>点击卡片配置 API Key</span>
                </div>
              </div>

              <div className="space-y-8">
                {(['model', 'embedding', 'reranker'] as ProviderCategory[]).map((category) => {
                  const InfoIcon = CATEGORY_INFO[category].icon
                  return (
                    <div key={category} className="bg-white rounded-2xl p-6 border border-gray-100 shadow-sm hover:shadow-md transition-shadow duration-300">
                      <div className="flex items-start gap-4 mb-6">
                        <div className="p-2 bg-gray-50 rounded-lg">
                          <InfoIcon className="h-5 w-5 text-gray-600" />
                        </div>
                        <div>
                          <h3 className="text-base font-medium text-gray-900">
                            {CATEGORY_INFO[category].title}
                          </h3>
                          <p className="text-sm text-gray-500 mt-0.5">
                            {CATEGORY_INFO[category].description}
                          </p>
                        </div>
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {groupedProviders[category].map((provider) => (
                          <ModelProviderCard
                            key={provider.id}
                            provider={provider}
                            onConfigure={handleConfigure}
                          />
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>

            {/* 系统设置区域 */}
            <section>
              <h2 className="text-lg font-semibold text-gray-900 mb-6 flex items-center gap-2">
                <Sliders className="h-5 w-5 text-blue-600" />
                系统参数
              </h2>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* 数据库设置 */}
                <div className="bg-white border border-gray-100 rounded-2xl p-6 shadow-sm hover:shadow-md transition-all duration-300 group">
                  <div className="flex items-center gap-3 mb-6">
                    <div className="p-2 bg-purple-50 text-purple-600 rounded-lg group-hover:bg-purple-100 transition-colors">
                      <Database className="h-5 w-5" />
                    </div>
                    <div>
                      <h3 className="font-medium text-gray-900">数据存储</h3>
                      <p className="text-xs text-gray-500 mt-0.5">数据库连接配置 (只读)</p>
                    </div>
                  </div>
                  
                  <div className="space-y-5">
                    <div>
                      <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                        PostgreSQL 连接
                      </label>
                      <div className="relative">
                        <input
                          type="text"
                          defaultValue="postgresql://postgres:***@localhost:5432/mimirq"
                          className="w-full pl-3 pr-10 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-600 font-mono focus:outline-none cursor-not-allowed"
                          readOnly
                        />
                        <div className="absolute right-3 top-2.5">
                          <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" title="已连接"></div>
                        </div>
                      </div>
                    </div>
                    
                    <div>
                      <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                        Milvus 向量库
                      </label>
                      <div className="relative">
                        <input
                          type="text"
                          defaultValue="localhost:19530"
                          className="w-full pl-3 pr-10 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-600 font-mono focus:outline-none cursor-not-allowed"
                          readOnly
                        />
                         <div className="absolute right-3 top-2.5">
                          <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" title="已连接"></div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* RAG 参数设置 */}
                <div className="bg-white border border-gray-100 rounded-2xl p-6 shadow-sm hover:shadow-md transition-all duration-300 group">
                  <div className="flex items-center gap-3 mb-6">
                    <div className="p-2 bg-orange-50 text-orange-600 rounded-lg group-hover:bg-orange-100 transition-colors">
                      <Sliders className="h-5 w-5" />
                    </div>
                    <div>
                      <h3 className="font-medium text-gray-900">检索策略</h3>
                      <p className="text-xs text-gray-500 mt-0.5">RAG 流程默认参数</p>
                    </div>
                  </div>

                  <div className="space-y-5">
                    <div>
                      <div className="flex justify-between items-center mb-2">
                        <label className="text-sm font-medium text-gray-700">Top K</label>
                        <span className="text-xs bg-gray-100 px-2 py-0.5 rounded text-gray-600">默认: 5</span>
                      </div>
                      <input
                        type="range"
                        min="1"
                        max="20"
                        defaultValue={5}
                        className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                      />
                      <p className="text-xs text-gray-400 mt-2">
                        每次检索返回的最相关文档片段数量
                      </p>
                    </div>

                    <div>
                      <div className="flex justify-between items-center mb-2">
                         <label className="text-sm font-medium text-gray-700">相似度阈值</label>
                         <span className="text-xs bg-gray-100 px-2 py-0.5 rounded text-gray-600">默认: 0.7</span>
                      </div>
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.1"
                        defaultValue={0.7}
                        className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                      />
                      <p className="text-xs text-gray-400 mt-2">
                        过滤掉相关性得分低于此值的片段
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </section>
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
