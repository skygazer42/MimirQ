/**
 * 模型提供商卡片组件
 */
'use client'

import { useState } from 'react'
import { Check, Settings, ExternalLink } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ProviderIcon } from '@/components/provider-icon'
import type { ModelProvider } from '@/types/models'

interface ModelProviderCardProps {
  provider: ModelProvider
  onConfigure: (provider: ModelProvider) => void
}

export function ModelProviderCard({ provider, onConfigure }: ModelProviderCardProps) {
  const [isHovered, setIsHovered] = useState(false)

  const borderColorClasses = {
    emerald: 'border-emerald-200 bg-emerald-50',
    orange: 'border-orange-200 bg-orange-50',
    blue: 'border-blue-200 bg-blue-50',
    purple: 'border-purple-200 bg-purple-50',
    sky: 'border-sky-200 bg-sky-50',
    indigo: 'border-indigo-200 bg-indigo-50',
    gray: 'border-gray-200 bg-gray-50',
    green: 'border-green-200 bg-green-50',
  }

  return (
    <div
      className={cn(
        'relative group bg-white border-2 rounded-xl p-6 transition-all cursor-pointer',
        provider.isConfigured
          ? `${borderColorClasses[provider.color as keyof typeof borderColorClasses]} border-2`
          : 'border-gray-200 hover:border-gray-300 hover:shadow-md'
      )}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onClick={() => onConfigure(provider)}
    >
      {/* 已配置标记 */}
      {provider.isConfigured && (
        <div className="absolute -top-2 -right-2 bg-green-500 text-white rounded-full p-1.5 shadow-lg">
          <Check className="h-4 w-4" />
        </div>
      )}

      {/* 图标和名称 */}
      <div className="flex items-start gap-4 mb-4">
        <div className="w-14 h-14 rounded-xl flex items-center justify-center bg-gray-50 border border-gray-100 overflow-hidden">
          <ProviderIcon providerId={provider.id} className="w-10 h-10 object-contain" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-lg font-semibold text-gray-900 mb-1">
            {provider.name}
          </h3>
          <p className="text-sm text-gray-600 line-clamp-2">
            {provider.description}
          </p>
        </div>
      </div>

      {/* 模型列表 */}
      <div className="space-y-2 mb-4">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">
          可用模型
        </p>
        <div className="flex flex-wrap gap-2">
          {provider.models.slice(0, 3).map((model) => (
            <span
              key={model.id}
              className="inline-flex items-center px-2.5 py-1 bg-gray-100 text-gray-700 text-xs rounded-md"
            >
              {model.displayName}
            </span>
          ))}
          {provider.models.length > 3 && (
            <span className="inline-flex items-center px-2.5 py-1 bg-gray-100 text-gray-500 text-xs rounded-md">
              +{provider.models.length - 3} 更多
            </span>
          )}
        </div>
      </div>

      {/* 操作按钮 */}
      <div
        className={cn(
          'flex items-center justify-between pt-4 border-t border-gray-200 transition-opacity',
          isHovered ? 'opacity-100' : 'opacity-60'
        )}
      >
        <button
          className="flex items-center gap-2 text-sm font-medium text-blue-600 hover:text-blue-700"
          onClick={(e) => {
            e.stopPropagation()
            onConfigure(provider)
          }}
        >
          <Settings className="h-4 w-4" />
          {provider.isConfigured ? '编辑配置' : '立即配置'}
        </button>

        {provider.isConfigured && provider.config?.apiBase && (
          <a
            href={provider.config.apiBase}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
            onClick={(e) => e.stopPropagation()}
          >
            <ExternalLink className="h-3 w-3" />
            <span>API 文档</span>
          </a>
        )}
      </div>
    </div>
  )
}
