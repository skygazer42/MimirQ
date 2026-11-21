/**
 * 模型配置对话框组件
 */
'use client'

import { useCallback, useId, useLayoutEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Eye, EyeOff, FlaskConical, Save, ChevronRight } from '@/components/icons'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { FeedbackToast } from '@/components/feedback-toast'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ProviderIcon } from '@/components/provider-icon'
import { cn } from '@/lib/utils'
import { settingsApi, type TestLLMResponse } from '@/lib/api/settings'
import { formatApiError } from '@/lib/api-errors'
import type { ModelConfigSubmission, ModelProvider } from '@/types/models'

type ModelEntryMode = 'preset' | 'custom'
type ModelConfigDraft = Omit<ModelConfigSubmission, 'model' | 'temperature' | 'timeout'> & {
  temperature: string
  timeout: number
}
const MODEL_CONNECTION_TOAST_ID = 'model-connection-feedback'

type ModelConfigDialogProps = {
  provider: ModelProvider | null
  open: boolean
  saving?: boolean
  onClose: () => void
  onSave: (providerId: string, config: ModelConfigSubmission) => Promise<void>
}

function getDefaultApiBase(providerId: string): string {
  const defaults: Record<string, string> = {
    openai: 'https://api.openai.com/v1',
    'openai-embedding': 'https://api.openai.com/v1',
    anthropic: 'https://api.anthropic.com',
    deepseek: 'https://api.deepseek.com/v1',
    zhipu: 'https://open.bigmodel.cn/api/paas/v4',
    qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    'qwen-embedding': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    moonshot: 'https://api.moonshot.cn/v1',
    ollama: 'http://localhost:11434/v1',
    'ollama-embedding': 'http://localhost:11434/api/embed',
    ark: 'https://ark.cn-beijing.volces.com/api/v3',
    lingyiwanwu: 'https://api.lingyiwanwu.com/v1',
    qianfan: 'https://qianfan.baidubce.com/v2',
    siliconflow: 'https://api.siliconflow.cn/v1',
    openrouter: 'https://openrouter.ai/api/v1',
    together: 'https://api.together.xyz/v1',
  }
  return Object.hasOwn(defaults, providerId) ? defaults[providerId] : ''
}

function getProviderModelOptions(provider: ModelProvider) {
  const modelType = provider.category === 'model' ? 'chat' : provider.category
  return provider.models.filter((model) => model.type === modelType)
}

export function ModelConfigDialog({ provider, open, saving, onClose, onSave }: Readonly<ModelConfigDialogProps>) {
  const idPrefix = useId()
  const [config, setConfig] = useState<ModelConfigDraft>({
    apiKey: '',
    apiBase: '',
    temperature: '0.7',
    timeout: 60,
  })
  const [showApiKey, setShowApiKey] = useState(false)
  const [isTesting, setIsTesting] = useState(false)
  const [testResult, setTestResult] = useState<TestLLMResponse | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const testRequest = useRef<AbortController | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [modelEntryMode, setModelEntryMode] = useState<ModelEntryMode>('preset')
  const [presetModel, setPresetModel] = useState('')
  const [customModelId, setCustomModelId] = useState('')
  const apiKeyId = `${idPrefix}-apiKey`
  const apiBaseId = `${idPrefix}-apiBase`
  const modelPresetId = `${idPrefix}-model-preset`
  const modelCustomId = `${idPrefix}-model-custom`
  const modelHintId = `${idPrefix}-model-hint`
  const modelPanelId = `${idPrefix}-model-panel`
  const temperatureId = `${idPrefix}-temperature`

  const clearConnectionTest = useCallback(() => {
    testRequest.current?.abort()
    testRequest.current = null
    setIsTesting(false)
    setTestResult(null)
    toast.dismiss(MODEL_CONNECTION_TOAST_ID)
  }, [])

  useLayoutEffect(() => {
    if (!open || provider === null) return

    const modelOptions = getProviderModelOptions(provider)
    const defaultModel = modelOptions[0]?.name ?? ''
    const savedConfig = provider.config
    const savedModel = savedConfig?.model
    const savedApiBase = savedConfig?.apiBase
    const configuredModel = savedModel === undefined || savedModel === '' ? defaultModel : savedModel
    const usesPreset = modelOptions.some((model) => model.name === configuredModel)

    setConfig({
      apiKey: savedConfig?.apiKey ?? '',
      apiBase: savedApiBase === undefined || savedApiBase === '' ? getDefaultApiBase(provider.id) : savedApiBase,
      temperature: String(savedConfig?.temperature ?? 0.7),
      timeout: savedConfig?.timeout ?? 60,
    })
    setModelEntryMode(usesPreset || !configuredModel ? 'preset' : 'custom')
    setPresetModel(usesPreset ? configuredModel : defaultModel)
    setCustomModelId(usesPreset ? '' : configuredModel)
    clearConnectionTest()
    setSaveError(null)
    setShowAdvanced(false)
    setShowApiKey(false)

    return () => {
      testRequest.current?.abort()
      toast.dismiss(MODEL_CONNECTION_TOAST_ID)
    }
  }, [provider, open, clearConnectionTest])

  if (provider === null) return null

  const canTestConnection = provider.category === 'model'
  const hasMaskedApiKey = config.apiKey.includes('***')
  const model = modelEntryMode === 'preset' ? presetModel : customModelId
  const modelOptions = getProviderModelOptions(provider)
  const selectedPresetModel = modelOptions.find((option) => option.name === presetModel)
  const docsUrl = getProviderDocsUrl(provider.id)
  const apiBase = config.apiBase === '' ? getDefaultApiBase(provider.id) : config.apiBase
  const temperature = Number(config.temperature)
  const isTemperatureValid = config.temperature.trim() !== '' && Number.isFinite(temperature)

  function updateConfig(patch: Partial<ModelConfigDraft>) {
    clearConnectionTest()
    setConfig((current) => ({ ...current, ...patch }))
  }

  const handleModelModeChange = (nextMode: ModelEntryMode) => {
    if (nextMode === modelEntryMode) return
    clearConnectionTest()
    setModelEntryMode(nextMode)
  }

  const handleCustomModelChange = (value: string) => {
    clearConnectionTest()
    setCustomModelId(value)
  }

  const handleSave = async () => {
    if (!isTemperatureValid) {
      toast.error('请填写有效的 Temperature')
      return
    }
    clearConnectionTest()
    setSaveError(null)
    try {
      await onSave(provider.id, { ...config, apiBase, model, temperature })
    } catch (error) {
      setSaveError(formatApiError(error, '保存配置失败'))
    }
  }

  const handleTest = async () => {
    if (testRequest.current !== null) return
    if (config.apiKey.trim() === '' || hasMaskedApiKey) {
      toast.error('请输入实际的 API Key 后再测试')
      return
    }
    if (model.trim() === '') {
      toast.error('请选择或输入模型 ID')
      return
    }
    if (!isTemperatureValid) {
      toast.error('请填写有效的 Temperature')
      return
    }

    const controller = new AbortController()
    testRequest.current = controller
    setIsTesting(true)
    setTestResult(null)

    try {
      const result = await settingsApi.testLLM(
        {
          api_key: config.apiKey,
          api_base: apiBase,
          model,
          temperature,
          timeout: config.timeout,
          max_retries: 1,
        },
        { signal: controller.signal },
      )
      if (!controller.signal.aborted) setTestResult(result)
    } catch (error: unknown) {
      if (!controller.signal.aborted) {
        setTestResult({ success: false, message: formatApiError(error, '测试失败') })
      }
    } finally {
      if (!controller.signal.aborted) {
        testRequest.current = null
        setIsTesting(false)
      }
    }
  }

  let apiKeyRequired = true
  if (provider.category === 'embedding') {
    if (provider.id === 'local-embedding' || provider.id === 'ollama-embedding') apiKeyRequired = false
    else if (provider.id === 'openai-embedding') {
      try {
        apiKeyRequired = new URL(apiBase).hostname === 'api.openai.com'
      } catch {
        /* Keep API Key required until a valid custom endpoint is entered. */
      }
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !saving) onClose()
      }}
    >
      <DialogContent
        showCloseButton={!saving}
        className="sm:max-w-[600px] p-0 overflow-hidden gap-0 rounded-2xl border-0 shadow-strong"
      >
        {/* 头部 */}
        <div className="bg-muted/40 border-b border-border p-6 flex items-start gap-4">
          <div className="h-11 w-11 rounded-xl bg-card border border-border flex items-center justify-center shadow-sm flex-shrink-0">
            <ProviderIcon providerId={provider.id} className="size-8 object-contain" />
          </div>
          <div>
            <DialogTitle className="text-xl font-semibold text-foreground mb-1">配置 {provider.name}</DialogTitle>
            <DialogDescription className="leading-tight">{provider.description}</DialogDescription>
          </div>
        </div>

        <fieldset disabled={saving} className="min-w-0 p-6 space-y-6">
          {/* API Key */}
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <Label htmlFor={apiKeyId} className="text-sm font-medium text-foreground">
                API Key{' '}
                {apiKeyRequired ? (
                  <span className="text-destructive ml-1">*</span>
                ) : (
                  <span className="ml-1 font-normal text-muted-foreground">（可选）</span>
                )}
              </Label>
              {docsUrl !== undefined && (
                <a
                  href={docsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs font-medium text-primary hover:underline"
                >
                  获取 Key <span aria-hidden>→</span>
                </a>
              )}
            </div>
            <div className="relative">
              <Input
                id={apiKeyId}
                type={showApiKey ? 'text' : 'password'}
                value={config.apiKey}
                onChange={(event) => updateConfig({ apiKey: event.target.value })}
                placeholder={apiKeyRequired ? `输入 ${provider.name} API Key` : '服务需要认证时填写'}
                required={apiKeyRequired}
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
            {canTestConnection && hasMaskedApiKey && (
              <p className="text-xs text-muted-foreground">
                连接测试需要输入实际的 API Key。保存配置时可以保留已保存的密钥。
              </p>
            )}
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
              onChange={(event) => updateConfig({ apiBase: event.target.value })}
              placeholder="https://api.example.com/v1"
              className="font-mono"
            />
          </div>

          {/* Model */}
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <Label className="text-sm font-medium text-foreground">模型</Label>
              <span className="text-[11px] text-muted-foreground">请求字段：model</span>
            </div>

            <div
              role="group"
              aria-label="模型 ID 来源"
              className="grid grid-cols-2 gap-1 rounded-lg border border-border/60 bg-muted/35 p-1"
            >
              <button
                type="button"
                aria-pressed={modelEntryMode === 'preset'}
                aria-controls={modelPanelId}
                onClick={() => handleModelModeChange('preset')}
                className={cn(
                  'h-9 rounded-md px-3 text-sm font-medium transition-[background-color,color,box-shadow] motion-reduce:transition-none focus-ring',
                  modelEntryMode === 'preset'
                    ? 'bg-card text-foreground shadow-sm'
                    : 'text-muted-foreground hover:bg-card/55 hover:text-foreground',
                )}
              >
                推荐模型
              </button>
              <button
                type="button"
                aria-pressed={modelEntryMode === 'custom'}
                aria-controls={modelPanelId}
                onClick={() => handleModelModeChange('custom')}
                className={cn(
                  'h-9 rounded-md px-3 text-sm font-medium transition-[background-color,color,box-shadow] motion-reduce:transition-none focus-ring',
                  modelEntryMode === 'custom'
                    ? 'bg-card text-foreground shadow-sm'
                    : 'text-muted-foreground hover:bg-card/55 hover:text-foreground',
                )}
              >
                自定义模型 ID
              </button>
            </div>

            <div id={modelPanelId} className="space-y-2">
              {modelEntryMode === 'preset' ? (
                <>
                  <Label htmlFor={modelPresetId} className="sr-only">
                    推荐模型
                  </Label>
                  <Select
                    value={presetModel}
                    onValueChange={(nextModel) => {
                      clearConnectionTest()
                      setPresetModel(nextModel)
                    }}
                  >
                    <SelectTrigger id={modelPresetId} aria-describedby={modelHintId} className="h-11">
                      <SelectValue placeholder="选择推荐模型">
                        {selectedPresetModel?.displayName ?? presetModel}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {modelOptions.map((model) => (
                        <SelectItem key={model.id} value={model.name} className="py-2.5">
                          <span className="grid min-w-0 gap-0.5">
                            <span className="font-medium text-foreground">{model.displayName}</span>
                            <span className="truncate font-mono text-[11px] text-muted-foreground">{model.name}</span>
                          </span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </>
              ) : (
                <>
                  <Label htmlFor={modelCustomId} className="sr-only">
                    自定义模型 ID
                  </Label>
                  <Input
                    id={modelCustomId}
                    type="text"
                    value={model}
                    onChange={(event) => handleCustomModelChange(event.target.value)}
                    placeholder={
                      provider.id === 'ark' ? '例如 doubao-seed-2-0-lite-260428' : '输入服务商控制台中的完整模型 ID'
                    }
                    aria-describedby={modelHintId}
                    autoComplete="off"
                    spellCheck={false}
                    className="h-11 font-mono"
                  />
                </>
              )}

              <div className="rounded-lg border border-border/55 bg-muted/25 px-3 py-2.5">
                <div className="mb-1 flex items-center justify-between gap-3 text-[11px] text-muted-foreground">
                  <span>实际请求 ID</span>
                  <span>{modelEntryMode === 'preset' ? '推荐项' : '自定义'}</span>
                </div>
                <code className="block break-all text-[12px] font-medium text-foreground">
                  {model === '' ? '尚未填写' : model}
                </code>
              </div>
            </div>

            <p id={modelHintId} className="text-xs leading-relaxed text-muted-foreground">
              推荐清单用于快捷选择；若服务商按账号、地域或版本提供其他 ID，请切换到自定义，测试和保存时会原样发送。
            </p>
          </div>

          {canTestConnection && (
            <div>
              <button
                type="button"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors motion-reduce:transition-none group"
              >
                <ChevronRight className={cn('size-4 transition-transform', showAdvanced && 'rotate-90')} />
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
                      value={config.temperature}
                      onChange={(event) => updateConfig({ temperature: event.target.value })}
                      className="h-9 text-sm"
                    />
                  </div>
                </div>
              )}
            </div>
          )}

          <FeedbackToast
            type={testResult?.success ? 'success' : 'error'}
            message={testResult?.message}
            id={MODEL_CONNECTION_TOAST_ID}
          />
          {saveError !== null && (
            <p role="alert" className="text-sm text-destructive">
              {saveError}
            </p>
          )}
        </fieldset>

        <DialogFooter className="p-6 pt-2 bg-card">
          <div className="flex gap-3 w-full">
            {canTestConnection && (
              <Button
                variant="outline"
                onClick={handleTest}
                disabled={saving || config.apiKey.trim() === '' || hasMaskedApiKey || model.trim() === '' || isTesting}
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
            )}
            <Button
              onClick={handleSave}
              disabled={saving || (apiKeyRequired && config.apiKey.trim() === '') || model.trim() === ''}
              className="flex-1 rounded-xl h-11"
            >
              <Save className="size-4 mr-2" />
              {saving ? '保存中…' : '保存配置'}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function getProviderDocsUrl(providerId: string): string | undefined {
  const urls: Record<string, string | undefined> = {
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
  return urls[providerId]
}
