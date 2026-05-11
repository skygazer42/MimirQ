/**
 * 设置页面 - 系统配置管理
 */
'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { AppFrame } from '@/components/app-frame'
import { ModelConfigDialog } from '@/components/model-config-dialog'
import { Button } from '@/components/ui/button'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { FeatureFlagsSection } from './_sections/feature-flags-section'
import { FrontendPreferencesSection } from './_sections/frontend-preferences-section'
import { GovernanceSection } from './_sections/governance-section'
import { IndustryRulesSection } from './_sections/industry-rules-section'
import { LtrModelRegistrySection } from './_sections/ltr-model-registry-section'
import { ModelProvidersSection } from './_sections/model-providers-section'
import { ObservabilitySection } from './_sections/observability-section'
import { ParserServicesSection } from './_sections/parser-services-section'
import { RagSection } from './_sections/rag-section'
import { RuntimeControlsSection } from './_sections/runtime-controls-section'
import { SystemStatusSection } from './_sections/system-status-section'
import { UrlIngestSection } from './_sections/url-ingest-section'
import { useSettingsPageState } from './use-settings-page-state'
import {
  CheckCircle2,
  Clock,
  LayoutGrid,
  Layers,
  Network,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  XCircle,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import { systemPageTokens } from '@/components/ui/system-page-tokens'

const SETTINGS_SECTIONS = [
  { id: 'sec-flags', label: '功能开关' },
  { id: 'sec-frontend', label: '前端偏好' },
  { id: 'sec-parsers', label: '解析服务' },
  { id: 'sec-status', label: '系统状态' },
  { id: 'sec-models', label: '模型接入' },
  { id: 'sec-ltr', label: 'LTR 模型' },
  { id: 'sec-rag', label: 'RAG 配置' },
  { id: 'sec-url', label: 'URL 采集' },
  { id: 'sec-governance', label: '数据治理' },
  { id: 'sec-industry-rules', label: '行业规则' },
  { id: 'sec-observability', label: '可观测性' },
  { id: 'sec-runtime', label: '运行时控制' },
] as const
const SETTINGS_CARD_CLASS =
  'rounded-[16px] border border-slate-200/75 bg-card shadow-sm'
const SETTINGS_OUTLINE_BUTTON =
  'h-8 rounded-[12px] border-slate-200 bg-card px-3 text-[12px] font-medium text-slate-700 shadow-sm hover:bg-slate-50'
const SETTINGS_PRIMARY_BUTTON =
  'h-8 rounded-[12px] bg-blue-600 px-3 text-[12px] font-medium text-info-foreground shadow-sm hover:bg-blue-700 disabled:opacity-80 disabled:bg-blue-500 disabled:text-info-foreground'

type SettingsMetricTone = 'blue' | 'green' | 'indigo' | 'slate'

type SettingsMetricItem = {
  label: string
  value: string | number
  icon: LucideIcon
  tone: SettingsMetricTone
  valueClassName?: string
}

const SETTINGS_METRIC_TONE_CLASS: Record<SettingsMetricTone, string> = {
  blue: 'bg-blue-50 text-blue-600',
  green: 'bg-emerald-50 text-emerald-600',
  indigo: 'bg-indigo-50 text-indigo-600',
  slate: 'bg-slate-100 text-slate-500',
}

function SettingsMetricStrip({
  items,
}: Readonly<{ items: readonly SettingsMetricItem[] }>) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => {
        const Icon = item.icon
        return (
          <div
            key={item.label}
            className={cn(
              SETTINGS_CARD_CLASS,
              'flex min-h-[68px] items-center gap-3 px-4 py-3'
            )}
          >
            <div
              className={cn(
                'flex size-9 shrink-0 items-center justify-center rounded-[13px]',
                SETTINGS_METRIC_TONE_CLASS[item.tone]
              )}
            >
              <Icon className="size-[17px]" />
            </div>
            <div className="min-w-0">
              <p className="text-[11px] font-medium text-slate-500">
                {item.label}
              </p>
              <p
                className={cn(
                  'mt-1 text-[16px] font-semibold leading-none text-slate-950',
                  item.valueClassName
                )}
              >
                {item.value}
              </p>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function SettingsToggleIndicator({ checked }: Readonly<{ checked: boolean }>) {
  return (
    <span
      className={cn(
        'flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition-colors',
        checked ? 'bg-blue-600' : 'bg-slate-300'
      )}
      aria-hidden="true"
    >
      <span
        className={cn(
          'size-4 rounded-full bg-card shadow-sm transition-transform',
          checked && 'translate-x-4'
        )}
      />
    </span>
  )
}

type EnhancementCardProps = {
  title: string
  description: string
  icon: LucideIcon
  checked: boolean
  onToggle: () => void
  tone: 'blue' | 'emerald'
  tags: string[]
}

function EnhancementCard({
  title,
  description,
  icon: Icon,
  checked,
  onToggle,
  tone,
  tags,
}: Readonly<EnhancementCardProps>) {
  const toneClass =
    tone === 'emerald'
      ? {
          card: checked
            ? 'border-emerald-200/90 bg-emerald-50/35'
            : 'border-slate-200 bg-card',
          icon: checked
            ? 'bg-emerald-100 text-emerald-600'
            : 'bg-slate-100 text-slate-500',
        }
      : {
          card: checked
            ? 'border-blue-200/90 bg-blue-50/35'
            : 'border-slate-200 bg-card',
          icon: checked
            ? 'bg-blue-100 text-blue-600'
            : 'bg-slate-100 text-slate-500',
        }

  return (
    <button
      type="button"
      aria-pressed={checked}
      onClick={onToggle}
      className={cn(
        'group flex min-h-[54px] w-full items-center justify-between gap-3 rounded-[13px] border px-3 py-2 text-left transition-[border-color,background-color,box-shadow] duration-150 focus-ring hover:border-blue-200/80 motion-reduce:transition-none',
        toneClass.card
      )}
    >
      <span className="flex min-w-0 items-center gap-2.5">
        <span
          className={cn(
            'flex size-6 shrink-0 items-center justify-center rounded-[10px]',
            toneClass.icon
          )}
        >
          <Icon className="size-3.5" />
        </span>
        <span className="min-w-0">
          <span className="block text-[12px] font-medium leading-4 text-slate-900">
            {title}
          </span>
          <span className="mt-0.5 block truncate text-[10.5px] leading-4 text-slate-500">
            {description}
          </span>
          {tags.length > 0 ? (
            <span className="mt-1 flex flex-wrap gap-1">
              {tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded-md border border-slate-200 bg-card/80 px-1.5 py-0.5 text-[10px] leading-[14px] text-slate-500"
                >
                  {tag}
                </span>
              ))}
            </span>
          ) : null}
        </span>
      </span>
      <SettingsToggleIndicator checked={checked} />
    </button>
  )
}

function RetrievalEnhancementSection({ state }: Readonly<{ state: any }>) {
  const bm25Enabled = Boolean(state.ragMerged?.bm25_index_enabled)
  const kgEnabled = state.getFeatureValue('kg_enabled')

  return (
    <section className="rounded-[16px] border border-slate-200/75 bg-card p-3.5 shadow-sm">
      <div className="mb-2.5">
        <h2 className="text-[13px] font-medium text-slate-950">
          关键词增强配置
        </h2>
        <p className="mt-0.5 text-[11px] leading-4 text-slate-500">
          绑定后端 RAG 与 KG 开关，控制关键词索引和图谱增强是否参与检索。
        </p>
      </div>
      <div className="grid grid-cols-1 gap-2.5 xl:grid-cols-2">
        <EnhancementCard
          title="BM25 关键词索引"
          description="启用关键词通道，对精确词匹配、标题和结构化段落更友好"
          icon={Search}
          checked={bm25Enabled}
          onToggle={() => state.updateRag({ bm25_index_enabled: !bm25Enabled })}
          tone="blue"
          tags={['RAG 配置', '真实后端字段']}
        />
        <EnhancementCard
          title="KG 知识图谱"
          description="启用实体、事件与关系索引，作为 RAG 上下文增强来源"
          icon={Network}
          checked={kgEnabled}
          onToggle={() => state.toggleFeature('kg_enabled')}
          tone="emerald"
          tags={['Feature Flag', 'KG_ENABLED']}
        />
      </div>
    </section>
  )
}

function useSettingsScrollSpy(sectionIds: readonly string[]) {
  const [activeId, setActiveId] = useState(sectionIds[0])
  const observerRef = useRef<IntersectionObserver | null>(null)

  useEffect(() => {
    observerRef.current?.disconnect()

    const visibleMap = new Map<string, number>()
    observerRef.current = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          visibleMap.set(entry.target.id, entry.intersectionRatio)
        }
        let best = sectionIds[0]
        let bestRatio = -1
        for (const id of sectionIds) {
          const ratio = visibleMap.get(id) ?? 0
          if (ratio > bestRatio) {
            bestRatio = ratio
            best = id
          }
        }
        if (bestRatio > 0) setActiveId(best)
      },
      {
        root: document.querySelector('[data-page-scroll-container]'),
        threshold: [0, 0.1, 0.25, 0.5],
      }
    )

    for (const id of sectionIds) {
      const el = document.getElementById(id)
      if (el) observerRef.current.observe(el)
    }

    return () => observerRef.current?.disconnect()
  }, [sectionIds])

  return activeId
}

export default function SettingsPage() {
  return (
    <TenantPermissionGate
      permission={TENANT_PERMISSIONS.SETTINGS_READ}
      pageName="系统设置"
    >
      <SettingsPageContent />
    </TenantPermissionGate>
  )
}

function SettingsPageContent() {
  const state = useSettingsPageState()
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const statusMetricItems: SettingsMetricItem[] = [
    {
      label: '配置分区',
      value: SETTINGS_SECTIONS.length,
      icon: LayoutGrid,
      tone: 'blue',
    },
    {
      label: '环境变量',
      value: state.hasChanges ? '待保存' : '已同步',
      icon: Layers,
      tone: 'green',
      valueClassName: state.hasChanges ? 'text-amber-600' : 'text-emerald-600',
    },
    {
      label: '保存状态',
      value: state.saving
        ? '保存中'
        : state.saveMessage?.type === 'success'
          ? '最近成功'
          : state.saveMessage?.type === 'error'
            ? '最近失败'
            : '空闲',
      icon: ShieldCheck,
      tone: state.saveMessage?.type === 'success' ? 'green' : 'indigo',
      valueClassName:
        state.saveMessage?.type === 'error'
          ? 'text-rose-600'
          : state.saving
            ? 'text-amber-600'
            : state.saveMessage?.type === 'success'
              ? 'text-emerald-600'
              : 'text-slate-950',
    },
    {
      label: '最近更新',
      value: state.lastUpdatedKeys.length
        ? `${state.lastUpdatedKeys.length} 项`
        : '0 秒前',
      icon: Clock,
      tone: 'blue',
    },
  ]

  return (
    <AppFrame>
      <PageScaffold
        title="设置与配置"
        badge="系统配置"
        description="统一管理功能开关、模型接入、检索增强生成参数（RAG）与运行时控制。"
        size="full"
        compact
        density="system-dense"
        headerClassName="[&_h1]:!text-[21px] [&_h1]:md:!text-[23px] [&_h1]:!font-semibold [&_h1]:!leading-tight [&_h1]:!tracking-[-0.026em] [&_[class*='rounded-full']]:border-blue-100 [&_[class*='rounded-full']]:bg-blue-50 [&_[class*='rounded-full']]:font-medium [&_[class*='rounded-full']]:normal-case [&_[class*='rounded-full']]: [&_[class*='rounded-full']]:text-blue-600"
        topClassName="pb-2.5"
        bodyClassName="pt-0.5"
        top={
          <div className="space-y-2">
            <SettingsMetricStrip items={statusMetricItems} />
            {state.loadError ? (
              <Alert
                variant="destructive"
                className="rounded-xl border-rose-200/80 bg-rose-50/70 shadow-none"
              >
                <XCircle className="size-4" />
                <div>
                  <AlertTitle>加载失败</AlertTitle>
                  <AlertDescription className="text-foreground/80">
                    {state.loadError}
                  </AlertDescription>
                </div>
              </Alert>
            ) : null}
            {state.saveMessage ? (
              <Alert
                variant={
                  state.saveMessage.type === 'success'
                    ? 'success'
                    : 'destructive'
                }
                className="rounded-xl border-border/70 shadow-none"
              >
                {state.saveMessage.type === 'success' ? (
                  <CheckCircle2 className="size-4" />
                ) : (
                  <XCircle className="size-4" />
                )}
                <div>
                  <AlertTitle>
                    {state.saveMessage.type === 'success'
                      ? '保存成功'
                      : '保存失败'}
                  </AlertTitle>
                  <AlertDescription className="text-foreground/80 space-y-2">
                    <div>{state.saveMessage.text}</div>
                    {state.saveMessage.type === 'success' &&
                    state.lastUpdatedKeys.length > 0 ? (
                      <div className={systemPageTokens.subtle}>
                        已更新：{state.lastUpdatedKeys.slice(0, 10).join(', ')}
                        {state.lastUpdatedKeys.length > 10
                          ? ` (+${state.lastUpdatedKeys.length - 10})`
                          : ''}
                      </div>
                    ) : null}
                  </AlertDescription>
                </div>
              </Alert>
            ) : null}
          </div>
        }
        actions={
          <>
            <Button
              variant="outline"
              onClick={state.refreshAll}
              disabled={state.loading}
              className={SETTINGS_OUTLINE_BUTTON}
            >
              <RefreshCw
                className={cn(
                  'size-4',
                  state.loading && 'animate-spin motion-reduce:animate-none'
                )}
              />
              刷新
            </Button>
            <Button
              onClick={state.saveSettings}
              disabled={!state.hasChanges || state.saving}
              className={SETTINGS_PRIMARY_BUTTON}
            >
              <Save
                className={cn(
                  'size-4',
                  state.saving && 'animate-pulse motion-reduce:animate-none'
                )}
              />
              {state.saving ? '保存中...' : '保存配置'}
            </Button>
          </>
        }
      >
        {state.loading ? (
          <div className="flex h-64 items-center justify-center">
            <RefreshCw className="size-8 animate-spin text-muted-foreground motion-reduce:animate-none" />
          </div>
        ) : (
          <SettingsContent
            state={state}
            parserBackend={parserBackend}
            setParserBackend={setParserBackend}
            chunkStrategy={chunkStrategy}
            setChunkStrategy={setChunkStrategy}
          />
        )}
      </PageScaffold>

      <ModelConfigDialog
        provider={state.selectedProvider}
        open={state.dialogOpen}
        onClose={() => state.setDialogOpen(false)}
        onSave={state.handleSaveConfig}
      />
    </AppFrame>
  )
}

function SettingsContent({
  state,
  parserBackend,
  setParserBackend,
  chunkStrategy,
  setChunkStrategy,
}: any) {
  const sectionIds = SETTINGS_SECTIONS.map((s) => s.id)
  const activeId = useSettingsScrollSpy(sectionIds)

  const scrollTo = useCallback((id: string) => {
    const el = document.getElementById(id)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  return (
    <div className="grid gap-4 lg:grid-cols-[176px_minmax(0,1fr)]">
      <nav
        className={cn(
          SETTINGS_CARD_CLASS,
          'sticky top-4 hidden shrink-0 self-start p-1.5 lg:block'
        )}
      >
        <ul className="space-y-0.5">
          {SETTINGS_SECTIONS.map((sec) => (
            <li key={sec.id}>
              <button
                type="button"
                onClick={() => scrollTo(sec.id)}
                className={cn(
                  'relative w-full rounded-[12px] px-3 py-2 text-left transition-colors',
                  'text-[12px] font-medium leading-[18px]',
                  activeId === sec.id
                    ? 'bg-blue-50/90 text-blue-600 before:absolute before:left-0 before:top-2 before:bottom-2 before:w-[3px] before:rounded-full before:bg-blue-600'
                    : 'text-slate-600 hover:bg-slate-50 hover:text-slate-950'
                )}
              >
                {sec.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <div className="min-w-0 space-y-4">
        <div id="sec-flags" className="scroll-mt-24 space-y-3">
          <RetrievalEnhancementSection state={state} />
          <FeatureFlagsSection
            editedFeatureFlags={state.editedFeatureFlags}
            getFeatureValue={state.getFeatureValue}
            toggleFeature={state.toggleFeature}
          />
        </div>

        <div id="sec-frontend" className="scroll-mt-24">
          <FrontendPreferencesSection
            parserBackend={parserBackend}
            setParserBackend={setParserBackend}
            chunkStrategy={chunkStrategy}
            setChunkStrategy={setChunkStrategy}
          />
        </div>

        <div id="sec-parsers" className="scroll-mt-24">
          <ParserServicesSection
            etl4llm={state.etl4llmMerged}
            marker={state.markerMerged}
            paddleVl={state.paddleVlMerged}
            textIn={state.textInMerged}
            magicPdf={state.magicPdfMerged}
            updateEtl4Llm={state.updateEtl4Llm}
            updateMarker={state.updateMarker}
            updatePaddleVL={state.updatePaddleVL}
            updateTextIn={state.updateTextIn}
            updateMagicPDF={state.updateMagicPDF}
          />
        </div>

        <div id="sec-status" className="scroll-mt-24">
          {state.status ? (
            <SystemStatusSection
              status={state.status}
              backendMeta={state.backendMeta}
            />
          ) : null}
        </div>

        <div id="sec-models" className="scroll-mt-24">
          <ModelProvidersSection
            groupedProviders={state.groupedProviders}
            onConfigure={state.handleConfigure}
          />
        </div>

        <div id="sec-ltr" className="scroll-mt-24">
          <LtrModelRegistrySection
            ltrError={state.ltrError}
            ltrMessage={state.ltrMessage}
            ltrUploading={state.ltrUploading}
            ltrUploadReady={state.ltrUploadReady}
            ltrUploadResetKey={state.ltrUploadResetKey}
            ltrLoading={state.ltrLoading}
            ltrBusyModelId={state.ltrBusyModelId}
            ltrModels={state.ltrModels}
            onRegister={state.registerLtrModel}
            onRefreshList={state.refreshLtrModels}
            onRollback={state.rollbackLtrModel}
            onActivate={state.activateLtrModel}
            onModelFileChange={state.setLtrUploadModelFile}
            onManifestFileChange={state.setLtrUploadManifestFile}
            formatBytes={state.formatBytes}
            formatTime={state.formatTime}
            shortId={state.shortId}
          />
        </div>

        <div id="sec-rag" className="scroll-mt-24">
          <RagSection rag={state.ragMerged} updateRag={state.updateRag} />
        </div>

        <div id="sec-url" className="scroll-mt-24">
          <UrlIngestSection
            urlIngest={state.urlIngestMerged}
            updateUrlIngest={state.updateUrlIngest}
          />
        </div>

        <div id="sec-governance" className="scroll-mt-24">
          <GovernanceSection
            isGovernanceEnabled={state.isGovernanceEnabled}
            isPiiAnonymizeEnabled={state.isPiiAnonymizeEnabled}
            isSecretsRedactEnabled={state.isSecretsRedactEnabled}
            isQuarantineOnDropEnabled={state.isQuarantineOnDropEnabled}
            updateGovernance={state.updateGovernance}
          />
        </div>

        <div id="sec-industry-rules" className="scroll-mt-24">
          <IndustryRulesSection />
        </div>

        <div id="sec-observability" className="scroll-mt-24">
          <ObservabilitySection
            observability={state.observabilityMerged}
            updateObservability={state.updateObservability}
          />
        </div>

        <div id="sec-runtime" className="scroll-mt-24">
          <RuntimeControlsSection
            chat={state.chatMerged}
            updateChat={state.updateChat}
            cache={state.cacheMerged}
            updateCache={state.updateCache}
            safety={state.safetyMerged}
            updateSafety={state.updateSafety}
            langgraph={state.langGraphMerged}
            updateLangGraph={state.updateLangGraph}
          />
        </div>
      </div>
    </div>
  )
}
