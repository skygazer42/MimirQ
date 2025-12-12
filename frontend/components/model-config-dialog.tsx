/**
 * 模型配置对话框组件
 */
'use client'

import { useState, useEffect } from 'react'
import { Eye, EyeOff, AlertCircle, CheckCircle2, FlaskConical, Save, ChevronRight } from 'lucide-react'
import {
  Dialog,
  DialogContent,
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
  const [showAdvanced, setShowAdvanced] = useState(false)

  useEffect(() => {
    if (provider?.config) {
      setConfig(provider.config)
    } else if (provider) {
      setConfig({
        apiKey: '',
        apiBase: getDefaultApiBase(provider.id),
        temperature: 0.7,
        maxTokens: 4096,
        timeout: 60,
      })
    }
    setTestResult(null)
    setShowAdvanced(false)
  }, [provider, open])

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
          ? '连接成功！配置有效'
          : '连接失败，请检查 API Key',
      })
      setIsTesting(false)
    }, 1500)
  }

  if (!provider) return null

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[550px] p-0 overflow-hidden gap-0 rounded-2xl border-0 shadow-2xl">
        {/* 头部 */}
        <div className="bg-gray-50/50 border-b border-gray-100 p-6 flex items-start gap-4">
          <div className="w-14 h-14 rounded-xl bg-white border border-gray-100 flex items-center justify-center shadow-sm flex-shrink-0">
            <ProviderIcon providerId={provider.id} className="w-9 h-9 object-contain" />
          </div>
          <div>
            <DialogTitle className="text-xl font-bold text-gray-900 mb-1">
              配置 {provider.name}
            </DialogTitle>
            <p className="text-sm text-gray-500 leading-tight">
              {provider.description}
            </p>
          </div>
        </div>

        <div className="p-6 space-y-6">
          {/* API Key */}
          <div className="space-y-2">
            <label className="text-sm font-semibold text-gray-700 flex justify-between">
              API Key <span className="text-red-500 ml-1">*</span>
              <a
                href={getProviderDocsUrl(provider.id)}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs font-normal text-blue-600 hover:text-blue-700 hover:underline"
              >
                获取 Key →
              </a>
            </label>
            <div className="relative group">
              <input
                type={showApiKey ? 'text' : 'password'}
                value={config.apiKey}
                onChange={(e) =>
                  setConfig({ ...config, apiKey: e.target.value })
                }
                placeholder={`输入 ${provider.name} API Key`}
                className="w-full pl-4 pr-10 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-100 focus:border-blue-400 outline-none transition-all text-sm font-mono"
              />
              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 p-1 rounded-md hover:bg-gray-100 transition-colors"
              >
                {showApiKey ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>

          {/* API Base URL */}
          <div className="space-y-2">
            <label className="text-sm font-semibold text-gray-700">
              API Base URL
            </label>
            <input
              type="text"
              value={config.apiBase}
              onChange={(e) =>
                setConfig({ ...config, apiBase: e.target.value })
              }
              placeholder="https://api.example.com/v1"
              className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-100 focus:border-blue-400 outline-none transition-all text-sm font-mono text-gray-600"
            />
          </div>

          {/* 高级设置开关 */}
          <div>
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-2 text-sm font-medium text-gray-500 hover:text-gray-900 transition-colors group"
            >
              <ChevronRight className={cn("h-4 w-4 transition-transform", showAdvanced && "rotate-90")} />
              高级设置
            </button>
            
            {showAdvanced && (
              <div className="mt-4 grid grid-cols-2 gap-4 animate-in slide-in-from-top-2 duration-200">
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-gray-500">Temperature</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max="2"
                    value={config.temperature}
                    onChange={(e) => setConfig({ ...config, temperature: parseFloat(e.target.value) })}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:bg-white focus:border-blue-400 outline-none"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-gray-500">Max Tokens</label>
                  <input
                    type="number"
                    value={config.maxTokens}
                    onChange={(e) => setConfig({ ...config, maxTokens: parseInt(e.target.value) })}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:bg-white focus:border-blue-400 outline-none"
                  />
                </div>
              </div>
            )}
          </div>

          {/* 测试结果 */}
          {testResult && (
            <div
              className={cn(
                'flex items-center gap-3 p-3 rounded-xl border animate-in fade-in zoom-in-95 duration-200',
                testResult.success
                  ? 'bg-green-50/50 border-green-100 text-green-700'
                  : 'bg-red-50/50 border-red-100 text-red-700'
              )}
            >
              {testResult.success ? (
                <CheckCircle2 className="h-5 w-5 flex-shrink-0" />
              ) : (
                <AlertCircle className="h-5 w-5 flex-shrink-0" />
              )}
              <span className="text-sm font-medium">{testResult.message}</span>
            </div>
          )}
        </div>

        <DialogFooter className="p-6 pt-2 bg-white">
          <div className="flex gap-3 w-full">
            <Button
              variant="outline"
              onClick={handleTest}
              disabled={!config.apiKey || isTesting}
              className="flex-1 rounded-xl h-11 border-gray-200 hover:bg-gray-50 hover:text-gray-900"
            >
              {isTesting ? (
                <span className="animate-pulse">测试中...</span>
              ) : (
                <>
                  <FlaskConical className="h-4 w-4 mr-2" />
                  测试连接
                </>
              )}
            </Button>
            <Button 
              onClick={handleSave} 
              disabled={!config.apiKey}
              className="flex-1 rounded-xl h-11 bg-blue-600 hover:bg-blue-700 shadow-lg shadow-blue-100"
            >
              <Save className="h-4 w-4 mr-2" />
              保存配置
            </Button>
          </div>
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
