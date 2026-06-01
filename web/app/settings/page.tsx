/**
 * 设置页面 - 系统配置管理
 */
'use client'

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { AppFrame } from '@/components/app-frame'
import { ModelConfigDialog } from '@/components/model-config-dialog'
import { Button } from '@/components/ui/button'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { FeatureFlagsSection } from './_sections/feature-flags-section'
import { DifyIntegrationSection } from './_sections/dify-integration-section'
import { FrontendPreferencesSection } from './_sections/frontend-preferences-section'
import { GovernanceSection } from './_sections/governance-section'
import { IndustryRulesSection } from './_sections/industry-rules-section'
import { LtrModelRegistrySection } from './_sections/ltr-model-registry-section'
import { ModelProvidersSection } from './_sections/model-providers-section'
import { NavigationVisibilitySection } from './_sections/navigation-visibility-section'
import { ObservabilitySection } from './_sections/observability-section'
import { ParserServicesSection } from './_sections/parser-services-section'
import { RagSection } from './_sections/rag-section'
import { RuntimeControlsSection } from './_sections/runtime-controls-section'
import { SystemStatusSection } from './_sections/system-status-section'
import { UrlIngestSection } from './_sections/url-ingest-section'
import { useSettingsPageState } from './use-settings-page-state'
import { SettingsSwitchIndicator } from '@/components/settings/settings-switch'
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
import { useTenantAccess } from '@/hooks/use-tenant-access'
import { tenantAccessIsAdmin } from '@/lib/navigation-visibility'
import { settingsTextTokens } from '@/components/ui/system-page-tokens'

type SettingsSectionDefinition = {
  id: string
  label: string
  hint: string
  adminOnly?: boolean
}

const SETTINGS_SECTIONS: readonly SettingsSectionDefinition[] = [
  { id: 'sec-status', label: '系统状态', hint: '后端连通性与运行状态' },
  { id: 'sec-models', label: '模型接入', hint: 'LLM / Embedding / Rerank 服务商' },
  { id: 'sec-flags', label: '功能开关', hint: 'RAG/KG 能力开关与依赖提示' },
  { id: 'sec-frontend', label: '前端偏好', hint: '本地浏览器偏好，不直接写后端' },
  { id: 'sec-navigation', label: '导航权限', hint: '普通用户入口可见性控制', adminOnly: true },
  { id: 'sec-parsers', label: '高级解析', hint: '高级解析器地址、超时与解析参数' },
  { id: 'sec-rag', label: 'RAG 配置', hint: '检索、召回与生成参数' },
  { id: 'sec-ltr', label: 'LTR 模型', hint: '排序模型注册、回滚和启用' },
  { id: 'sec-dify', label: 'Dify 接入', hint: '外部知识库访问、API Key 与数据集绑定', adminOnly: true },
  { id: 'sec-url', label: 'URL 采集', hint: '网页采集与清洗策略', adminOnly: true },
  { id: 'sec-governance', label: '数据治理', hint: 'PII、密钥、隔离与清洗策略' },
  { id: 'sec-industry-rules', label: '行业规则', hint: '行业规则包与解析模板' },
  { id: 'sec-observability', label: '可观测性', hint: '监控、审计和诊断开关', adminOnly: true },
  { id: 'sec-runtime', label: '运行控制', hint: '聊天、缓存、安全和流程编排' },
] as const

const SETTINGS_SECTION_BY_ID = Object.fromEntries(
  SETTINGS_SECTIONS.map((section) => [section.id, section])
) as Record<string, SettingsSectionDefinition>
const SETTINGS_CARD_CLASS =
  'rounded-[16px] border border-border/60 bg-card/82 shadow-sm'
const SETTINGS_OUTLINE_BUTTON =
  'h-8 rounded-[12px] border-border/60 bg-card/82 px-3 text-[12px] font-medium text-foreground shadow-sm hover:bg-muted/45'
const SETTINGS_PRIMARY_BUTTON =
  'h-8 rounded-[12px] bg-primary px-3 text-[12px] font-medium text-primary-foreground shadow-sm hover:bg-primary/90 disabled:bg-primary/55 disabled:opacity-80 disabled:text-primary-foreground'

type SettingsMetricTone = 'blue' | 'green' | 'indigo' | 'slate'

type SettingsMetricItem = {
  label: string
  value: string | number
  icon: LucideIcon
  tone: SettingsMetricTone
  valueClassName?: string
}

const SETTINGS_METRIC_TONE_CLASS: Record<SettingsMetricTone, string> = {
  blue: 'bg-primary/10 text-primary',
  green: 'bg-success/10 text-success',
  indigo: 'bg-accent/10 text-accent',
  slate: 'bg-muted text-muted-foreground',
}

function getSaveStatusLabel(
  saving: boolean,
  saveMessageType?: string
): string {
  if (saving) return '保存中'
  if (saveMessageType === 'success') return '最近成功'
  if (saveMessageType === 'error') return '最近失败'
  return '空闲'
}

function getSaveStatusTone(saveMessageType?: string): SettingsMetricTone {
  if (saveMessageType === 'success') return 'green'
  return 'indigo'
}

function getSaveStatusValueClassName(
  saving: boolean,
  saveMessageType?: string
): string {
  if (saveMessageType === 'error') return 'text-destructive'
  if (saving) return 'text-warning'
  if (saveMessageType === 'success') return 'text-success'
  return 'text-foreground'
}

function SettingsMetricStrip({
  items,
}: Readonly<{ items: readonly SettingsMetricItem[] }>) {
  return (
    <div
      data-testid="settings-metric-strip"
      className="flex flex-wrap items-center gap-1.5 rounded-[16px] border border-border/60 bg-card/82 p-1.5 shadow-[0_8px_24px_hsl(var(--foreground)/0.03)]"
    >
      {items.map((item) => {
        const Icon = item.icon
        return (
          <div
            key={item.label}
            className="flex min-h-9 flex-1 basis-[150px] items-center gap-2 rounded-[12px] border border-border/50 bg-muted/28 px-2.5 py-1.5"
          >
            <div
              className={cn(
                'flex size-6 shrink-0 items-center justify-center rounded-[9px]',
                SETTINGS_METRIC_TONE_CLASS[item.tone]
              )}
            >
              <Icon className="size-3.5" />
            </div>
            <div className="flex min-w-0 flex-1 items-baseline justify-between gap-2">
              <p className="truncate text-[11px] font-semibold text-muted-foreground">
                {item.label}
              </p>
              <p
                className={cn(
                  'shrink-0 text-[13px] font-semibold leading-none text-foreground',
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

function SettingsSaveFeedback({
  message,
  updatedKeys,
}: Readonly<{
  message: { type: 'success' | 'error'; text: string; detail?: string }
  updatedKeys: string[]
}>) {
  if (message.type === 'error') {
    return (
      <Alert
        variant="destructive"
        className="rounded-xl border-destructive/25 bg-destructive/10 shadow-none"
      >
        <XCircle className="size-4" />
        <div>
          <AlertTitle>保存失败</AlertTitle>
          <AlertDescription className="text-foreground/80">
            {message.text}
          </AlertDescription>
        </div>
      </Alert>
    )
  }

  const visibleKeys = updatedKeys.slice(0, 4)
  const extraCount = Math.max(0, updatedKeys.length - visibleKeys.length)

  return (
    <div className="rounded-[16px] border border-success/25 bg-[linear-gradient(135deg,hsl(var(--success)/0.12),hsl(var(--card)/0.90))] px-3.5 py-3 shadow-[0_10px_30px_hsl(var(--success)/0.06)]">
      <div className="flex items-start gap-3">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-[11px] border border-success/25 bg-success/15 text-success">
          <CheckCircle2 className="size-4" />
        </div>
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[13px] font-semibold leading-none text-foreground">
              已保存
            </p>
            {message.detail ? (
              <span className="rounded-full border border-success/25 bg-card/85 px-2 py-0.5 text-[10px] font-medium text-success">
                少量配置需重启服务
              </span>
            ) : null}
          </div>
          <p className="text-[12px] leading-5 text-muted-foreground">{message.text}</p>
          {message.detail ? (
            <p className="text-[11.5px] font-medium leading-[18px] text-muted-foreground">
              {message.detail}
            </p>
          ) : null}
          {updatedKeys.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] font-semibold text-muted-foreground">
                本次更新
              </span>
              {visibleKeys.map((key) => (
                <span
                  key={key}
                  className="rounded-full border border-border/60 bg-card/85 px-2 py-0.5 font-mono text-[10px] text-muted-foreground"
                >
                  {key}
                </span>
              ))}
              {extraCount > 0 ? (
                <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">
                  +{extraCount} 项
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
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
            ? 'border-success/30 bg-success/10'
            : 'border-border/60 bg-card',
          icon: checked
            ? 'bg-success/15 text-success'
            : 'bg-muted text-muted-foreground',
        }
      : {
          card: checked
            ? 'border-primary/30 bg-primary/10'
            : 'border-border/60 bg-card',
          icon: checked
            ? 'bg-primary/15 text-primary'
            : 'bg-muted text-muted-foreground',
        }

  return (
    <button
      type="button"
      aria-pressed={checked}
      onClick={onToggle}
      className={cn(
        'group flex min-h-[54px] w-full items-center justify-between gap-3 rounded-[13px] border px-3 py-2 text-left transition-[border-color,background-color,box-shadow] duration-150 focus-ring hover:border-primary/30 motion-reduce:transition-none',
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
          <span className="block text-[12px] font-semibold leading-4 text-foreground">
            {title}
          </span>
          <span className="mt-0.5 block truncate text-[10.5px] font-medium leading-4 text-muted-foreground">
            {description}
          </span>
          {tags.length > 0 ? (
            <span className="mt-1 flex flex-wrap gap-1">
              {tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded-md border border-border/60 bg-card/80 px-1.5 py-0.5 text-[10px] font-medium leading-[14px] text-muted-foreground"
                >
                  {tag}
                </span>
              ))}
            </span>
          ) : null}
        </span>
      </span>
      <SettingsSwitchIndicator checked={checked} />
    </button>
  )
}

function RetrievalEnhancementSection({ state }: Readonly<{ state: any }>) {
  const bm25Enabled = Boolean(state.ragMerged?.bm25_index_enabled)
  const kgEnabled = state.getFeatureValue('kg_enabled')

  return (
    <section className="rounded-[16px] border border-border/60 bg-card/82 p-3.5 shadow-sm">
      <div className="mb-2.5">
        <h2 className="text-[13px] font-semibold text-foreground">
          关键词增强配置
        </h2>
        <p className="mt-0.5 text-[11.5px] font-medium leading-[18px] text-muted-foreground">
          绑定后端 RAG 与 KG 开关，控制关键词索引和图谱增强是否参与检索
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

function SettingsSectionFrame({
  section,
  index,
  children,
  className,
}: Readonly<{
  section: SettingsSectionDefinition
  index: number
  children: ReactNode
  className?: string
}>) {
  return (
    <section
      id={section.id}
      aria-labelledby={`${section.id}-title`}
      className={cn(
        'relative scroll-mt-24 overflow-visible rounded-[20px] border border-border/60 bg-card/82 shadow-[0_14px_34px_hsl(var(--foreground)/0.035)]',
        'before:absolute before:-left-3 before:top-4 before:bottom-4 before:w-px before:rounded-full before:bg-primary/25',
        className
      )}
    >
      <div className="rounded-t-[20px] border-b border-border/50 bg-[linear-gradient(90deg,hsl(var(--muted)/0.38),hsl(var(--card)/0.88),hsl(var(--primary)/0.06))] px-4 py-3 ring-1 ring-inset ring-border/40">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-7 w-9 shrink-0 items-center justify-center rounded-[12px] border border-primary/20 bg-primary/10 text-[11px] font-black text-primary">
            {String(index + 1).padStart(2, '0')}
          </span>
          <div className="min-w-0">
            <h2
              id={`${section.id}-title`}
              className={cn(settingsTextTokens.sectionTitle, 'leading-tight')}
            >
              {section.label}
            </h2>
            <p className="mt-0.5 text-[11.5px] font-medium leading-[18px] text-muted-foreground">
              {section.hint}
            </p>
          </div>
        </div>
      </div>
      <div className="space-y-3 border-t border-border/35 p-3.5">{children}</div>
    </section>
  )
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
  const access = useTenantAccess()
  const isAdmin = tenantAccessIsAdmin(access.data)
  const visibleSections = useMemo(
    () => SETTINGS_SECTIONS.filter((section) => !section.adminOnly || isAdmin),
    [isAdmin]
  )
  const visibleSectionIndex = useMemo(
    () =>
      Object.fromEntries(
        visibleSections.map((section, index) => [section.id, index])
      ) as Record<string, number>,
    [visibleSections]
  )
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const statusMetricItems: SettingsMetricItem[] = [
    {
      label: '配置分区',
      value: visibleSections.length,
      icon: LayoutGrid,
      tone: 'blue',
    },
    {
      label: '环境变量',
      value: state.hasChanges ? '待保存' : '已同步',
      icon: Layers,
      tone: 'green',
      valueClassName: state.hasChanges ? 'text-warning' : 'text-success',
    },
    {
      label: '保存状态',
      value: getSaveStatusLabel(state.saving, state.saveMessage?.type),
      icon: ShieldCheck,
      tone: getSaveStatusTone(state.saveMessage?.type),
      valueClassName: getSaveStatusValueClassName(
        state.saving,
        state.saveMessage?.type
      ),
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
        iconImage="settings"
        description="统一管理功能开关、模型接入、检索增强生成参数（RAG）与运行控制"
        size="full"
        compact
        density="system-dense"
        headerClassName="[&_h1]:!text-[21px] [&_h1]:md:!text-[23px] [&_h1]:!font-semibold [&_h1]:!leading-tight [&_h1]:!tracking-[-0.026em] [&_[class*='rounded-full']]:border-primary/20 [&_[class*='rounded-full']]:bg-primary/10 [&_[class*='rounded-full']]:font-medium [&_[class*='rounded-full']]:normal-case [&_[class*='rounded-full']]:text-primary"
        topClassName="pb-2.5"
        bodyClassName="pt-0.5"
        top={
          <div className="space-y-2">
            <SettingsMetricStrip items={statusMetricItems} />
            {state.loadError ? (
              <Alert
                variant="destructive"
                className="rounded-xl border-destructive/25 bg-destructive/10 shadow-none"
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
              <SettingsSaveFeedback
                message={state.saveMessage}
                updatedKeys={state.lastUpdatedKeys}
              />
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
            visibleSections={visibleSections}
            visibleSectionIndex={visibleSectionIndex}
            isAdmin={isAdmin}
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
  visibleSections,
  visibleSectionIndex,
  isAdmin,
  parserBackend,
  setParserBackend,
  chunkStrategy,
  setChunkStrategy,
}: any) {
  const sectionIds = visibleSections.map((s: { id: string }) => s.id)
  const activeId = useSettingsScrollSpy(sectionIds)

  const scrollTo = useCallback((id: string) => {
    const el = document.getElementById(id)
    if (!el) return
    const main = document.getElementById('main-content')
    const scrollContainer = document.querySelector<HTMLElement>('[data-page-scroll-container]')
    if (!scrollContainer) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      return
    }

    // Keep the app shell fixed; only the page body should scroll when using
    // the settings side index. scrollIntoView can also move overflow-hidden
    // ancestors, which visually cuts off the right pane bottom.
    main?.scrollTo({ top: 0, left: 0, behavior: 'auto' })
    const containerRect = scrollContainer.getBoundingClientRect()
    const targetRect = el.getBoundingClientRect()
    const nextTop = targetRect.top - containerRect.top + scrollContainer.scrollTop - 8
    scrollContainer.scrollTo({ top: Math.max(0, nextTop), behavior: 'smooth' })
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
          {visibleSections.map((sec: { id: string; label: string }) => (
            <li key={sec.id}>
              <button
                type="button"
                onClick={() => scrollTo(sec.id)}
                className={cn(
                  'relative w-full rounded-[12px] px-3 py-2 text-left transition-colors',
                  'text-[12px] font-semibold leading-[18px]',
                  activeId === sec.id
                    ? 'bg-primary/10 text-primary before:absolute before:left-0 before:top-2 before:bottom-2 before:w-[3px] before:rounded-full before:bg-primary'
                    : 'text-foreground/78 hover:bg-muted/45 hover:text-foreground'
                )}
              >
                {sec.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <div className="min-w-0 space-y-6">
        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-status']}
          index={visibleSectionIndex['sec-status']}
        >
          {state.status ? (
            <SystemStatusSection
              status={state.status}
              backendMeta={state.backendMeta}
            />
          ) : null}
        </SettingsSectionFrame>

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-models']}
          index={visibleSectionIndex['sec-models']}
        >
          <ModelProvidersSection
            groupedProviders={state.groupedProviders}
            onConfigure={state.handleConfigure}
          />
        </SettingsSectionFrame>

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-flags']}
          index={visibleSectionIndex['sec-flags']}
          className="[&>div:last-child]:space-y-3"
        >
          <RetrievalEnhancementSection state={state} />
          <FeatureFlagsSection
            editedFeatureFlags={state.editedFeatureFlags}
            getFeatureValue={state.getFeatureValue}
            toggleFeature={state.toggleFeature}
          />
        </SettingsSectionFrame>

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-frontend']}
          index={visibleSectionIndex['sec-frontend']}
        >
          <FrontendPreferencesSection
            parserBackend={parserBackend}
            setParserBackend={setParserBackend}
            chunkStrategy={chunkStrategy}
            setChunkStrategy={setChunkStrategy}
          />
        </SettingsSectionFrame>

        {isAdmin ? (
          <SettingsSectionFrame
            section={SETTINGS_SECTION_BY_ID['sec-navigation']}
            index={visibleSectionIndex['sec-navigation']}
          >
            <NavigationVisibilitySection
              navigation={state.navigationMerged}
              updateNavigation={state.updateNavigation}
            />
          </SettingsSectionFrame>
        ) : null}

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-parsers']}
          index={visibleSectionIndex['sec-parsers']}
          className="[&>div:last-child]:space-y-4"
        >
          <ParserServicesSection
            mineru={state.mineruMerged}
            etl4llm={state.etl4llmMerged}
            marker={state.markerMerged}
            paddleVl={state.paddleVlMerged}
            textIn={state.textInMerged}
            magicPdf={state.magicPdfMerged}
            updateMinerU={state.updateMinerU}
            updateEtl4Llm={state.updateEtl4Llm}
            updateMarker={state.updateMarker}
            updatePaddleVL={state.updatePaddleVL}
            updateTextIn={state.updateTextIn}
            updateMagicPDF={state.updateMagicPDF}
          />
        </SettingsSectionFrame>

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-rag']}
          index={visibleSectionIndex['sec-rag']}
        >
          <RagSection rag={state.ragMerged} updateRag={state.updateRag} />
        </SettingsSectionFrame>

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-ltr']}
          index={visibleSectionIndex['sec-ltr']}
        >
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
        </SettingsSectionFrame>

        {isAdmin ? (
          <SettingsSectionFrame
            section={SETTINGS_SECTION_BY_ID['sec-dify']}
            index={visibleSectionIndex['sec-dify']}
          >
            <DifyIntegrationSection
              difyExternalKnowledge={state.difyExternalKnowledgeMerged}
              updateDifyExternalKnowledge={state.updateDifyExternalKnowledge}
            />
          </SettingsSectionFrame>
        ) : null}

        {isAdmin ? (
          <SettingsSectionFrame
            section={SETTINGS_SECTION_BY_ID['sec-url']}
            index={visibleSectionIndex['sec-url']}
          >
            <UrlIngestSection
              urlIngest={state.urlIngestMerged}
              updateUrlIngest={state.updateUrlIngest}
            />
          </SettingsSectionFrame>
        ) : null}

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-governance']}
          index={visibleSectionIndex['sec-governance']}
        >
          <GovernanceSection
            isGovernanceEnabled={state.isGovernanceEnabled}
            isPiiAnonymizeEnabled={state.isPiiAnonymizeEnabled}
            isSecretsRedactEnabled={state.isSecretsRedactEnabled}
            isQuarantineOnDropEnabled={state.isQuarantineOnDropEnabled}
            updateGovernance={state.updateGovernance}
          />
        </SettingsSectionFrame>

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-industry-rules']}
          index={visibleSectionIndex['sec-industry-rules']}
        >
          <IndustryRulesSection />
        </SettingsSectionFrame>

        {isAdmin ? (
          <SettingsSectionFrame
            section={SETTINGS_SECTION_BY_ID['sec-observability']}
            index={visibleSectionIndex['sec-observability']}
          >
            <ObservabilitySection
              observability={state.observabilityMerged}
              updateObservability={state.updateObservability}
            />
          </SettingsSectionFrame>
        ) : null}

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-runtime']}
          index={visibleSectionIndex['sec-runtime']}
        >
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
        </SettingsSectionFrame>
      </div>
    </div>
  )
}
