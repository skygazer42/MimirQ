/**
 * 设置页面 - 模型提供商配置
 */
'use client'

import { useState } from 'react'
import { Navbar } from '@/components/navbar'
import { ModelProviderCard } from '@/components/model-provider-card'
import { ModelConfigDialog } from '@/components/model-config-dialog'
import { MODEL_PROVIDERS } from '@/types/models'
import type { ModelProvider, ProviderConfig } from '@/types/models'

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

  const configuredCount = providers.filter((p) => p.isConfigured).length

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
            <div className="mt-4 flex items-center gap-6 text-sm">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 bg-green-500 rounded-full"></div>
                <span className="text-gray-600">
                  已配置 {configuredCount} 个
                </span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 bg-gray-300 rounded-full"></div>
                <span className="text-gray-600">
                  未配置 {providers.length - configuredCount} 个
                </span>
              </div>
            </div>
          </div>

          {/* 模型提供商网格 */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {providers.map((provider) => (
              <ModelProviderCard
                key={provider.id}
                provider={provider}
                onConfigure={handleConfigure}
              />
            ))}
          </div>

          {/* 帮助提示 */}
          <div className="mt-8 bg-blue-50 border border-blue-200 rounded-lg p-6">
            <h3 className="text-lg font-semibold text-blue-900 mb-2">
              💡 配置提示
            </h3>
            <ul className="space-y-2 text-sm text-blue-800">
              <li>• 点击任意卡片进行配置,输入对应的 API Key</li>
              <li>• 支持使用自定义 API Base URL (如代理服务)</li>
              <li>• 配置完成后可以测试连接确保可用性</li>
              <li>• 本地 Embedding 模型无需 API Key,开箱即用</li>
            </ul>
          </div>

          {/* 其他设置部分 */}
          <div className="mt-12">
            <h2 className="text-2xl font-bold text-gray-900 mb-6">系统设置</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* 数据库设置 */}
              <div className="bg-white border border-gray-200 rounded-lg p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                  🗄️ 数据库连接
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
                  🔍 检索参数
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
