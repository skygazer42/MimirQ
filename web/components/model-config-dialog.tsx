/**
 * 模型配置对话框组件
 */
'use client'

import { useEffect, useId, useState } from 'react'
import { Eye, EyeOff, AlertCircle, CheckCircle2, FlaskConical, Save, ChevronRight } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ProviderIcon } from '@/components/provider-icon'
import { cn } from '@/lib/utils'
import { settingsApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import type { ModelProvider, ProviderConfig } from '@/types/models'

interface ModelConfigDialogProps {
  provider: ModelProvider | null
  open: boolean
  onClose: () => void
  onSave: (providerId: string, config: ProviderConfig) => void
}

function getDefaultApiBase(providerId: string): string {
  const defaults: Record<string, string> = {
    openai: 'https://api.openai.com/v1',
    anthropic: 'https://api.anthropic.com',
    deepseek: 'https://api.deepseek.com/v1',
    zhipu: 'https://open.bigmodel.cn/api/paas/v4',
    qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    'qwen-embedding': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    moonshot: 'https://api.moonshot.cn/v1',
    ollama: 'http://localhost:11434/v1',
    ark: 'https://ark.cn-beijing.volces.com/api/v3',
    lingyiwanwu: 'https://api.lingyiwanwu.com/v1',
    qianfan: 'https://qianfan.baidubce.com/v2',
    siliconflow: 'https://api.siliconflow.cn/v1',
    openrouter: 'https://openrouter.ai/api/v1',
    together: 'https://api.together.xyz/v1',
  }
  return defaults[providerId] || ''
}

export function ModelConfigDialog({
  provider,
  open,
  onClose,
  onSave,
}: Readonly<ModelConfigDialogProps>) {
  const idPrefix = useId()
  const [config, setConfig] = useState<ProviderConfig>({
    apiKey: '',
    apiBase: '',
    model: '',
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
  const apiKeyId = `${idPrefix}-apiKey`
  const apiBaseId = `${idPrefix}-apiBase`
  const modelId = `${idPrefix}-model`
  const modelOptionsId = `${idPrefix}-model-options`
  const modelHintId = `${idPrefix}-model-hint`
  const temperatureId = `${idPrefix}-temperature`
  const maxTokensId = `${idPrefix}-maxTokens`

  useEffect(() => {
    const modelOptions = provider
      ? provider.models.filter((m) => {
          if (provider.category === 'model') return m.type === 'chat'
          if (provider.category === 'embedding') return m.type === 'embedding'
          if (provider.category === 'reranker') return m.type === 'reranker'
          return true
        })
      : []
    const defaultModel = modelOptions[0]?.name || ''

    if (provider?.config) {
      setConfig({
        apiKey: provider.config.apiKey || '',
        apiBase: provider.config.apiBase || getDefaultApiBase(provider.id),
        model: provider.config.model || defaultModel,
        temperature: provider.config.temperature ?? 0.7,
        maxTokens: provider.config.maxTokens ?? 4096,
        timeout: provider.config.timeout ?? 60,
      })
    } else if (provider) {
      setConfig({
        apiKey: '',
        apiBase: getDefaultApiBase(provider.id),
        model: defaultModel,
        temperature: 0.7,
        maxTokens: 4096,
        timeout: 60,
      })
    }
    setTestResult(null)
    setShowAdvanced(false)
  }, [provider, open])

  const handleSave = () => {
    if (!provider) return
    onSave(provider.id, config)
    onClose()
  }

  const handleTest = async () => {
    setIsTesting(true)
    setTestResult(null)

    try {
      if (!provider) return
      if (provider.category !== 'model') {
        setTestResult({ success: false, message: '目前仅支持测试聊天模型连接' })
        return
      }
      if (!config.apiKey) {
        setTestResult({ success: false, message: '请先填写 API Key' })
        return
      }
      if (!config.model) {
        setTestResult({ success: false, message: '请选择模型' })
        return
      }

      const result = await settingsApi.testLLM({
        api_key: config.apiKey,
        api_base: config.apiBase || getDefaultApiBase(provider.id),
        model: config.model,
        temperature: config.temperature,
        timeout: config.timeout,
        max_retries: 1,
      })
      setTestResult({ success: !!result.success, message: result.message })
    } catch (e: unknown) {
      setTestResult({ success: false, message: formatApiError(e, '测试失败') })
    } finally {
      setIsTesting(false)
    }
  }

  if (!provider) return null

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[550px] p-0 overflow-hidden gap-0 rounded-2xl border-0 shadow-strong">
        {/* 头部 */}
        <div className="bg-muted/40 border-b border-border p-6 flex items-start gap-4">
          <div className="h-11 w-11 rounded-xl bg-card border border-border flex items-center justify-center shadow-sm flex-shrink-0">
            <ProviderIcon providerId={provider.id} className="size-8 object-contain" />
          </div>
          <div>
            <DialogTitle className="text-xl font-semibold text-foreground mb-1">
              配置 {provider.name}
            </DialogTitle>
            <p className="text-sm text-muted-foreground leading-tight">
              {provider.description}
            </p>
          </div>
        </div>

        <div className="p-6 space-y-6">
          {/* API Key */}
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <Label htmlFor={apiKeyId} className="text-sm font-medium text-foreground">
                API Key <span className="text-destructive ml-1">*</span>
              </Label>
              <a
                href={getProviderDocsUrl(provider.id)}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs font-medium text-primary hover:underline"
              >
                获取 Key <span aria-hidden>→</span>
              </a>
            </div>
            <div className="relative">
              <Input
                id={apiKeyId}
                type={showApiKey ? 'text' : 'password'}
                value={config.apiKey}
                onChange={(e) => setConfig({ ...config, apiKey: e.target.value })}
                placeholder={`输入 ${provider.name} API Key`}
                className="pr-10 font-mono"
              />
              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                aria-label={showApiKey ? '隐藏 API Key' : '显示 API Key'}
                title={showApiKey ? '隐藏 API Key' : '显示 API Key'}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors motion-reduce:transition-none focus-ring"
              >
                {showApiKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
          </div>

          {/* API Base URL */}
          <div className="space-y-2">
            <Label htmlFor={apiBaseId} className="text-sm font-medium text-foreground">
              API Base URL
            </Label>
            <Input
              id={apiBaseId}
              type="text"
              value={config.apiBase}
              onChange={(e) => setConfig({ ...config, apiBase: e.target.value })}
              placeholder="https://api.example.com/v1"
              className="font-mono"
            />
          </div>

          {/* Model */}
          <div className="space-y-2">
            <Label htmlFor={modelId} className="text-sm font-medium text-foreground">
              模型调用 ID
            </Label>
            <Input
              id={modelId}
              type="text"
              list={modelOptionsId}
              value={config.model || ''}
              onChange={(e) => setConfig({ ...config, model: e.target.value })}
              placeholder={provider.id === 'ark' ? '例如 doubao-seed-2-0-lite-260428' : '输入或选择模型 ID'}
              aria-describedby={modelHintId}
              className="font-mono"
            />
            <datalist id={modelOptionsId}>
              {provider.models
                .filter((m) => {
                  if (provider.category === 'model') return m.type === 'chat'
                  if (provider.category === 'embedding') return m.type === 'embedding'
                  if (provider.category === 'reranker') return m.type === 'reranker'
                  return true
                })
                .map((model) => (
                  <option key={model.id} value={model.name} label={model.displayName} />
                ))}
            </datalist>
            <p id={modelHintId} className="text-xs leading-relaxed text-muted-foreground">
              可选择推荐项，也可输入服务商要求的完整模型 ID；保存和测试时会原样发送。
            </p>
          </div>

          {/* 高级设置开关 */}
          <div>
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors motion-reduce:transition-none group"
            >
              <ChevronRight className={cn("size-4 transition-transform", showAdvanced && "rotate-90")} />
              高级设置
            </button>
            
            {showAdvanced && (
              <div className="mt-4 grid grid-cols-2 gap-4 motion-safe:animate-in motion-safe:slide-in-from-top-2 motion-safe:duration-200">
                <div className="space-y-1.5">
                  <Label htmlFor={temperatureId} className="text-xs font-medium text-muted-foreground">
                    Temperature
                  </Label>
                  <Input
                    id={temperatureId}
                    type="number"
                    step="0.1"
                    min="0"
                    max="2"
                    value={config.temperature}
                    onChange={(e) => setConfig({ ...config, temperature: Number.parseFloat(e.target.value) })}
                    className="h-9 text-sm"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={maxTokensId} className="text-xs font-medium text-muted-foreground">
                    Max Tokens
                  </Label>
                  <Input
                    id={maxTokensId}
                    type="number"
                    value={config.maxTokens}
                    onChange={(e) => setConfig({ ...config, maxTokens: Number.parseInt(e.target.value) })}
                    className="h-9 text-sm"
                  />
                </div>
              </div>
            )}
          </div>

          {/* 测试结果 */}
          {testResult && (
            <Alert
              variant={testResult.success ? "success" : "destructive"}
              className="animate-in fade-in zoom-in-95 duration-200 motion-reduce:animate-none"
            >
              {testResult.success ? (
                <CheckCircle2 className="size-5" />
              ) : (
                <AlertCircle className="size-5" />
              )}
              <div>
                <AlertDescription className="text-foreground font-medium">
                  {testResult.message}
                </AlertDescription>
              </div>
            </Alert>
          )}
        </div>

        <DialogFooter className="p-6 pt-2 bg-card">
          <div className="flex gap-3 w-full">
            <Button
              variant="outline"
              onClick={handleTest}
              disabled={!config.apiKey || !config.model || isTesting}
              className="flex-1 rounded-xl h-11"
            >
              {isTesting ? (
                <span className="animate-pulse motion-reduce:animate-none">测试中...</span>
              ) : (
                <>
                  <FlaskConical className="size-4 mr-2" />
                  测试连接
                </>
              )}
            </Button>
            <Button 
              onClick={handleSave} 
              disabled={!config.apiKey || !config.model}
              className="flex-1 rounded-xl h-11"
            >
              <Save className="size-4 mr-2" />
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
    'qwen-embedding': 'https://dashscope.console.aliyun.com/',
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
