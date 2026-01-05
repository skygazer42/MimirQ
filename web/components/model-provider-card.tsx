/**
 * 模型提供商卡片组件
 */
'use client'

import { Settings, ExternalLink, CheckCircle2, CircleDashed } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ProviderIcon } from '@/components/provider-icon'
import type { ModelProvider } from '@/types/models'

interface ModelProviderCardProps {
  provider: ModelProvider
  onConfigure: (provider: ModelProvider) => void
}

export function ModelProviderCard({ provider, onConfigure }: ModelProviderCardProps) {
  return (
    <div
      className={cn(
        'group relative bg-white border rounded-xl p-5 transition-all duration-300 cursor-pointer flex flex-col h-full',
        provider.isConfigured
          ? 'border-blue-200/60 shadow-sm ring-1 ring-blue-50'
          : 'border-gray-200 hover:border-blue-300 hover:shadow-md hover:-translate-y-0.5'
      )}
      onClick={() => onConfigure(provider)}
    >
      {/* 头部：Logo 和状态 */}
      <div className="flex justify-between items-start mb-4">
        <div className="w-12 h-12 rounded-xl flex items-center justify-center bg-gray-50 border border-gray-100 group-hover:scale-105 transition-transform duration-300">
          <ProviderIcon providerId={provider.id} className="w-8 h-8 object-contain" />
        </div>
        
        <div className={cn(
          "px-2.5 py-1 rounded-full text-[11px] font-medium flex items-center gap-1.5 transition-colors",
          provider.isConfigured 
            ? "bg-green-50 text-green-700 border border-green-100"
            : "bg-gray-50 text-gray-500 border border-gray-100 group-hover:bg-blue-50 group-hover:text-blue-600 group-hover:border-blue-100"
        )}>
          {provider.isConfigured ? (
            <>
              <CheckCircle2 className="h-3 w-3" />
              <span>已连接</span>
            </>
          ) : (
            <>
              <CircleDashed className="h-3 w-3" />
              <span>未配置</span>
            </>
          )}
        </div>
      </div>

      {/* 名称和描述 */}
      <div className="mb-4 flex-1">
        <h3 className="text-base font-bold text-gray-900 mb-1.5 group-hover:text-blue-700 transition-colors">
          {provider.name}
        </h3>
        <p className="text-xs text-gray-500 leading-relaxed line-clamp-2">
          {provider.description}
        </p>
      </div>

      {/* 模型标签 */}
      <div className="flex flex-wrap gap-1.5 mb-5">
        {provider.models.slice(0, 3).map((model) => (
          <span
            key={model.id}
            className="inline-flex items-center px-2 py-0.5 bg-gray-50 text-gray-600 border border-gray-100 text-[10px] font-medium rounded-md"
          >
            {model.displayName}
          </span>
        ))}
        {provider.models.length > 3 && (
          <span className="inline-flex items-center px-2 py-0.5 bg-gray-50 text-gray-400 border border-gray-100 text-[10px] rounded-md">
            +{provider.models.length - 3}
          </span>
        )}
      </div>

      {/* 底部操作 */}
      <div className="pt-3 border-t border-gray-50 flex items-center justify-between text-xs mt-auto">
        <span className={cn(
          "font-medium flex items-center gap-1.5 transition-colors",
          provider.isConfigured ? "text-blue-600" : "text-gray-400 group-hover:text-blue-600"
        )}>
          <Settings className="h-3.5 w-3.5" />
          {provider.isConfigured ? '管理配置' : '去配置'}
        </span>
        
        {/* 仅在 Hover 时显示的箭头或图标 */}
        <div className="opacity-0 group-hover:opacity-100 transition-opacity transform translate-x-[-5px] group-hover:translate-x-0 duration-300 text-blue-400">
           →
        </div>
      </div>
    </div>
  )
}
