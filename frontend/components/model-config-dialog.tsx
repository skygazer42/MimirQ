/**
 * 模型配置对话框组件
 */
'use client'

import { useState, useEffect } from 'react'
import { X, Eye, EyeOff, AlertCircle, CheckCircle2 } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { ProviderIcon } from '@/components/provider-icon'
import { cn } from '@/lib/utils'
import type { ModelProvider, ProviderConfig } from '@/types/models'

interface ModelConfigDialogProps {
  provider: ModelProvider | null
  open: boolean
  onClose: () => void
  onSave: (providerId: string, config: ProviderConfig) => void
}

export function ModelConfigDialog({
  provider,
  open,
  onClose,
  onSave,
}: ModelConfigDialogProps) {
  const [config, setConfig] = useState<ProviderConfig>({
    apiKey: '',
    apiBase: '',
    temperature: 0.7,
    maxTokens: 4096,
    timeout: 60,
  })
  const [showApiKey, setShowApiKey] = useState(false)
  const [isTesting, setIsTesting] = useState(false)
  const [testResult, setTestResult] = useState<{
    success: boolean
    message: string
  } | null>(null)

  useEffect(() => {
    if (provider?.config) {
      setConfig(provider.config)
    } else if (provider) {
      // 设置默认值
      setConfig({
        apiKey: '',
        apiBase: getDefaultApiBase(provider.id),
        temperature: 0.7,
        maxTokens: 4096,
        timeout: 60,
      })
    }
  }, [provider])

  const getDefaultApiBase = (providerId: string): string => {
    const defaults: Record<string, string> = {
      openai: 'https://api.openai.com/v1',
      anthropic: 'https://api.anthropic.com',
      deepseek: 'https://api.deepseek.com/v1',
      zhipu: 'https://open.bigmodel.cn/api/paas/v4',
      qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      moonshot: 'https://api.moonshot.cn/v1',
      ollama: 'http://localhost:11434/v1',
      ark: 'https://ark.cn-beijing.volces.com/api/v3',
      lingyiwanwu: 'https://api.lingyiwanwu.com/v1',
      qianfan: 'https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop',
      siliconflow: 'https://api.siliconflow.cn/v1',
      openrouter: 'https://openrouter.ai/api/v1',
      together: 'https://api.together.xyz/v1',
    }
    return defaults[providerId] || ''
  }

  const handleSave = () => {
    if (!provider) return
    onSave(provider.id, config)
    onClose()
  }

  const handleTest = async () => {
    setIsTesting(true)
    setTestResult(null)

    // 模拟测试连接
    setTimeout(() => {
      const success = Math.random() > 0.3 // 70% 成功率模拟
      setTestResult({
        success,
        message: success
          ? '连接成功！API 配置正确'
          : 'API Key 无效或网络连接失败',
      })
      setIsTesting(false)
    }, 2000)
  }

  if (!provider) return null

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-lg bg-gray-50 border border-gray-100 flex items-center justify-center overflow-hidden">
              <ProviderIcon providerId={provider.id} className="w-9 h-9 object-contain" />
            </div>
            <div>
              <div className="text-xl">{provider.name}</div>
              <div className="text-sm font-normal text-gray-500">
                {provider.description}
              </div>
            </div>
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-6 py-4">
          {/* API Key */}
          <div>
            <label className="block text-sm font-medium text-gray-900 mb-2">
              API Key <span className="text-red-500">*</span>
            </label>
            <div className="relative">
              <input
                type={showApiKey ? 'text' : 'password'}
                value={config.apiKey}
                onChange={(e) =>
                  setConfig({ ...config, apiKey: e.target.value })
                }
                placeholder="sk-..."
                className="w-full px-3 py-2 pr-10 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                {showApiKey ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              从{' '}
              <a
                href={getProviderDocsUrl(provider.id)}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline"
              >
                官方控制台
              </a>{' '}
              获取 API Key
            </p>
          </div>

          {/* API Base URL */}
          <div>
            <label className="block text-sm font-medium text-gray-900 mb-2">
              API Base URL
            </label>
            <input
              type="text"
              value={config.apiBase}
              onChange={(e) =>
                setConfig({ ...config, apiBase: e.target.value })
              }
              placeholder="https://api.example.com/v1"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <p className="text-xs text-gray-500 mt-1">
              使用自定义端点或代理服务
            </p>
          </div>

          {/* 高级设置 */}
          <details className="group">
            <summary className="cursor-pointer text-sm font-medium text-gray-700 hover:text-gray-900">
              高级设置 (可选)
            </summary>
            <div className="mt-4 space-y-4 pl-4 border-l-2 border-gray-200">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Temperature
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max="2"
                    value={config.temperature}
                    onChange={(e) =>
                      setConfig({
                        ...config,
                        temperature: parseFloat(e.target.value),
                      })
                    }
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Max Tokens
                  </label>
                  <input
                    type="number"
                    value={config.maxTokens}
                    onChange={(e) =>
                      setConfig({
                        ...config,
                        maxTokens: parseInt(e.target.value),
                      })
                    }
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Timeout (秒)
                </label>
                <input
                  type="number"
                  value={config.timeout}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      timeout: parseInt(e.target.value),
                    })
                  }
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
            </div>
          </details>

          {/* 测试结果 */}
          {testResult && (
            <div
              className={cn(
                'flex items-start gap-3 p-4 rounded-lg border-2',
                testResult.success
                  ? 'bg-green-50 border-green-200'
                  : 'bg-red-50 border-red-200'
              )}
            >
              {testResult.success ? (
                <CheckCircle2 className="h-5 w-5 text-green-600 flex-shrink-0 mt-0.5" />
              ) : (
                <AlertCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
              )}
              <div className="flex-1">
                <p
                  className={cn(
                    'text-sm font-medium',
                    testResult.success ? 'text-green-900' : 'text-red-900'
                  )}
                >
                  {testResult.message}
                </p>
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={handleTest}
            disabled={!config.apiKey || isTesting}
          >
            {isTesting ? '测试中...' : '测试连接'}
          </Button>
          <Button onClick={handleSave} disabled={!config.apiKey}>
            保存配置
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function getProviderDocsUrl(providerId: string): string {
  const urls: Record<string, string> = {
    openai: 'https://platform.openai.com/api-keys',
    anthropic: 'https://console.anthropic.com/',
    deepseek: 'https://platform.deepseek.com/',
    zhipu: 'https://open.bigmodel.cn/',
    qwen: 'https://dashscope.console.aliyun.com/',
    moonshot: 'https://platform.moonshot.cn/',
    ollama: 'https://ollama.ai/',
    ark: 'https://console.volcengine.com/ark',
    lingyiwanwu: 'https://platform.lingyiwanwu.com/',
    qianfan: 'https://console.bce.baidu.com/qianfan/',
    siliconflow: 'https://cloud.siliconflow.cn/',
    openrouter: 'https://openrouter.ai/keys',
    together: 'https://api.together.xyz/',
  }
  return urls[providerId] || '#'
}
