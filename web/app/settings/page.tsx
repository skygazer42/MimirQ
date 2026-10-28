/**
 * 设置页面 - 系统配置管理
 */
'use client'

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { FeedbackToast } from '@/components/feedback-toast'
import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { AppFrame } from '@/components/app-frame'
import { ModelConfigDialog } from '@/components/model-config-dialog'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { FeatureFlagsSection } from './_sections/feature-flags-section'
import { DifyIntegrationSection } from './_sections/dify-integration-section'
import { FrontendPreferencesSection } from './_sections/frontend-preferences-section'
import { GovernanceSection } from './_sections/governance-section'
import { IndustryRulesSection } from './_sections/industry-rules-section'
import { ModelProvidersSection } from './_sections/model-providers-section'
import { NavigationVisibilitySection } from './_sections/navigation-visibility-section'
import { ObservabilitySection } from './_sections/observability-section'
import { ParserServicesSection } from './_sections/parser-services-section'
import { RagSection } from './_sections/rag-section'
import { RuntimeControlsSection } from './_sections/runtime-controls-section'
import { SystemStatusSection } from './_sections/system-status-section'
import { useSettingsPageState } from './use-settings-page-state'
import { SettingsSwitchIndicator } from '@/components/settings/settings-switch'
import {
  Activity,
  AuditLog,
  ArrowLeft,
  Blocks,
  ChevronRight,
  DataGovernance,
  Gauge,
  Layout,
  Link,
  Loader2,
  Model,
  Parsing,
  RefreshCw,
  RuleSet,
  Search,
  SlidersHorizontal,
  XCircle,
  type PlatformIcon,
} from '@/components/icons'
import { cn } from '@/lib/utils'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import { useTenantAccess } from '@/hooks/use-tenant-access'
import { tenantAccessIsAdmin } from '@/lib/navigation-visibility'
import { Link as AppLink } from '@/i18n/navigation'
import { useAuth } from '@/hooks/use-auth'
import styles from './settings.module.css'

type SettingsSectionDefinition = {
  id: string
  label: string
  hint: string
  group: 'general' | 'pipeline' | 'integrations' | 'operations'
  icon: PlatformIcon
  adminOnly?: boolean
}

const SETTINGS_SECTION_GROUPS = [
  { id: 'general', label: '通用' },
  { id: 'pipeline', label: '内容与检索' },
  { id: 'integrations', label: '外部集成' },
  { id: 'operations', label: '治理与运行' },
] as const

const SETTINGS_SECTIONS: readonly SettingsSectionDefinition[] = [
  { id: 'sec-status', label: '系统状态', hint: '查看数据库、模型和解析服务的可用状态。', group: 'general', icon: Activity },
  { id: 'sec-models', label: '模型接入', hint: '配置语言、嵌入和重排序模型。', group: 'general', icon: Model },
  { id: 'sec-flags', label: '功能开关', hint: '外部解析器还需启动相应服务。', group: 'general', icon: Blocks },
  { id: 'sec-frontend', label: '处理偏好', hint: '保存在当前浏览器，用于新上传和预览。', group: 'general', icon: SlidersHorizontal },
  { id: 'sec-navigation', label: '导航显示', hint: '选择普通成员可见的功能入口，具体操作仍受成员权限限制。', group: 'general', icon: Layout, adminOnly: true },
  { id: 'sec-parsers', label: '解析服务', hint: '设置各解析器的服务地址、超时和解析参数。', group: 'pipeline', icon: Parsing },
  { id: 'sec-rag', label: '检索与生成', hint: '调整召回、重排序和内容切分参数。', group: 'pipeline', icon: Search },
  { id: 'sec-dify', label: 'Dify 接入', hint: '外部知识库访问、API Key 与数据集绑定', group: 'integrations', icon: Link, adminOnly: true },
  { id: 'sec-governance', label: '数据治理', hint: '文档脱敏、隔离与复核。', group: 'operations', icon: DataGovernance },
  { id: 'sec-industry-rules', label: '行业规则', hint: '术语词库、匹配规则与意图规则。', group: 'operations', icon: RuleSet },
  { id: 'sec-observability', label: '监控与审计', hint: '设置运行记录、审计和诊断选项。', group: 'operations', icon: AuditLog, adminOnly: true },
  { id: 'sec-runtime', label: '运行控制', hint: '聊天、缓存、安全和流程编排', group: 'operations', icon: Gauge },
] as const

const SETTINGS_SECTION_BY_ID = Object.fromEntries(
  SETTINGS_SECTIONS.map((section) => [section.id, section])
) as Record<string, SettingsSectionDefinition>
type SettingsPageState = ReturnType<typeof useSettingsPageState>
type ParserBackendPreference = ReturnType<typeof useParserBackendPreference>
type ChunkStrategyPreference = ReturnType<typeof useChunkStrategyPreference>
type SettingsContentProps = {
  state: SettingsPageState
  visibleSections: SettingsSectionDefinition[]
  isAdmin: boolean
  parserBackend: ParserBackendPreference['parserBackend']
  setParserBackend: ParserBackendPreference['setParserBackend']
  chunkStrategy: ChunkStrategyPreference['chunkStrategy']
  setChunkStrategy: ChunkStrategyPreference['setChunkStrategy']
}

function RetrievalEnhancementSection({ state }: Readonly<{ state: SettingsPageState }>) {
  const enabled = Boolean(state.ragMerged?.bm25_index_enabled)
  return (
    <button
      type="button"
      aria-pressed={enabled}
      onClick={() => state.updateRag({ bm25_index_enabled: !enabled })}
      className="flex min-h-16 w-full items-center justify-between gap-4 border-b border-border/50 py-3 text-left transition-colors hover:bg-muted/40 focus-ring"
    >
      <span className="flex min-w-0 items-start gap-3">
        <Search className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0">
          <span className="block text-sm font-medium text-foreground">BM25 关键词索引</span>
          <span className="mt-1 block text-[13px] leading-5 text-muted-foreground">使用关键词匹配补充语义检索，适合精确词和标题查询。</span>
        </span>
      </span>
      <SettingsSwitchIndicator checked={enabled} />
    </button>
  )
}

function SettingsSectionFrame({
  section,
  children,
  className,
  hidden = false,
}: Readonly<{
  section: SettingsSectionDefinition
  children: ReactNode
  className?: string
  hidden?: boolean
}>) {
  return (
    <section
      id={section.id}
      hidden={hidden}
      aria-labelledby={`${section.id}-title`}
      className={cn(
        styles.section,
        className
      )}
    >
      <header className={styles.sectionHeader}>
        <h2 id={`${section.id}-title`} className={styles.sectionTitle}>{section.label}</h2>
        <p className={styles.sectionHint}>{section.hint}</p>
      </header>
      <div className={cn(styles.sectionBody, 'space-y-5')}>{children}</div>
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
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  return (
    <AppFrame navigationVariant="rail" showBackground={false} className={styles.workspace}>
      <SettingsContent
        state={state}
        visibleSections={visibleSections}
        isAdmin={isAdmin}
        parserBackend={parserBackend}
        setParserBackend={setParserBackend}
        chunkStrategy={chunkStrategy}
        setChunkStrategy={setChunkStrategy}
      />

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
  isAdmin,
  parserBackend,
  setParserBackend,
  chunkStrategy,
  setChunkStrategy,
}: Readonly<SettingsContentProps>) {
  const sectionIds = useMemo(() => visibleSections.map((section) => section.id), [visibleSections])
  const [selectedId, setSelectedId] = useState('sec-frontend')
  useEffect(() => {
    const readSection = () => {
      const id = window.location.hash.slice(1)
      if (sectionIds.includes(id)) setSelectedId(id)
    }
    readSection()
    window.addEventListener('hashchange', readSection)
    return () => window.removeEventListener('hashchange', readSection)
  }, [sectionIds])
  const activeId = sectionIds.includes(selectedId) ? selectedId : sectionIds[0]
  const sectionGroups = useMemo(
    () => SETTINGS_SECTION_GROUPS.map((group) => ({
      ...group,
      sections: visibleSections.filter((section) => section.group === group.id),
    })).filter((group) => group.sections.length > 0),
    [visibleSections]
  )
  const directoryRef = useRef<HTMLElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const { isDevMode, user } = useAuth()
  const activeSection = SETTINGS_SECTION_BY_ID[activeId] || visibleSections[0]
  const activeGroup = SETTINGS_SECTION_GROUPS.find((group) => group.id === activeSection.group)

  useEffect(() => {
    const revealCurrentSection = () => {
      const directory = directoryRef.current
      const current = directory?.querySelector<HTMLElement>('[aria-current="location"]')
      if (!directory?.clientHeight || !current) return
      const directoryBounds = directory.getBoundingClientRect()
      const currentBounds = current.getBoundingClientRect()
      if (currentBounds.top < directoryBounds.top + 4) {
        directory.scrollTop += currentBounds.top - directoryBounds.top - 4
      } else if (currentBounds.bottom > directoryBounds.bottom - 4) {
        directory.scrollTop += currentBounds.bottom - directoryBounds.bottom + 4
      }
    }
    revealCurrentSection()
    window.addEventListener('resize', revealCurrentSection)
    return () => window.removeEventListener('resize', revealCurrentSection)
  }, [activeId])

  const positionSection = useCallback(() => {
    scrollRef.current?.scrollTo({ top: 0, behavior: 'auto' })
  }, [])

  useLayoutEffect(() => {
    positionSection()
  }, [activeId, state.loading, positionSection])

  const selectSection = (id: string) => {
    if (!sectionIds.includes(id)) return
    setSelectedId(id)
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}#${id}`)
    if (id === activeId) positionSection()
  }

  return (
    <div className={styles.layout} data-settings-workspace>
      <aside className={cn(styles.directory, 'hidden xl:flex')}>
        <header><h1 className={styles.directoryTitle}>系统设置</h1></header>
        <nav ref={directoryRef} aria-label="设置分区" data-settings-directory className={cn(styles.directoryScroll, 'xl:block')}>
          {sectionGroups.map((group) => (
            <div key={group.id} className={styles.directoryGroup} role="group" aria-labelledby={`settings-directory-${group.id}`}>
              <h2 id={`settings-directory-${group.id}`} className={styles.groupName}>{group.label}</h2>
              <ul>
                {group.sections.map((section) => {
                  const isActive = activeId === section.id
                  return (
                    <li key={section.id}>
                      <button
                        type="button"
                        disabled={state.loading}
                        onClick={() => selectSection(section.id)}
                        aria-controls={section.id}
                        aria-current={isActive ? 'location' : undefined}
                        className={cn(styles.directoryItem, 'focus-ring')}
                      >
                        <span>{section.label}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
        </nav>
        <AppLink href="/" className={cn(styles.returnLink, 'focus-ring')}><ArrowLeft className="size-3.5" />返回工作区</AppLink>
      </aside>

      <div className={styles.main}>
        <header className={styles.toolbar}>
          <nav aria-label="当前位置" className={styles.breadcrumb}>
            <span>系统设置</span><ChevronRight className="size-3" /><span>{activeGroup?.label}</span><ChevronRight className="size-3" /><strong>{activeSection.label}</strong>
          </nav>
          <div className={styles.toolbarStatus}>
            <div role="status" aria-live="polite" className="flex min-h-8 items-center gap-2">
              {state.saveError ? <Button variant="ghost" size="sm" onClick={() => void state.retrySave()} className="h-11 text-destructive sm:h-8">重试保存</Button> : state.saving || state.hasChanges ? <><Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" />正在保存…</> : null}
            </div>
            <span className={styles.account}>{isDevMode ? '开发模式' : user?.username || user?.email}</span>
          </div>
        </header>
        <div data-settings-mobile-directory className={cn(styles.mobileDirectory, 'xl:hidden')}>
            <Select value={activeId} disabled={state.loading} onValueChange={selectSection}>
              <SelectTrigger aria-label="设置分区" className="h-11 w-full bg-background text-base"><SelectValue /></SelectTrigger>
              <SelectContent>
                {sectionGroups.map((group) => <SelectGroup key={group.id}><SelectLabel>{group.label}</SelectLabel>{group.sections.map((section) => <SelectItem key={section.id} value={section.id} className="min-h-11">{section.label}</SelectItem>)}</SelectGroup>)}
              </SelectContent>
            </Select>
        </div>
        {state.loadError ? <div className={cn(styles.alerts, 'space-y-2')}>
            {state.loadError ? <Alert variant="destructive" className="rounded-md border-destructive/25 bg-destructive/10 shadow-none"><XCircle className="size-4" /><div><AlertTitle>加载失败</AlertTitle><AlertDescription>{state.loadError}</AlertDescription></div></Alert> : null}
        </div> : null}
        <FeedbackToast type="error" id="settings-save-error" message={state.saveError ? `自动保存失败：${state.saveError.replace(/\s*\(request_id=[^)]+\)/g, '')}。修改已保留，可重试。` : null} />
        <div ref={scrollRef} className={styles.scroll} data-page-scroll-container>
          {state.loading ? <div className={styles.loading}><RefreshCw className="size-7 animate-spin motion-reduce:animate-none" aria-label="正在加载设置" /></div> : <>
        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-status']}
          hidden={activeId !== 'sec-status'}
        >
          {state.status ? (
            <SystemStatusSection
              status={state.status}
              backendMeta={state.backendMeta}
            />
          ) : <p role="status" className="text-[13px] leading-5 text-muted-foreground">暂时无法读取服务状态。</p>}
        </SettingsSectionFrame>

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-models']}
          hidden={activeId !== 'sec-models'}
        >
          <ModelProvidersSection
            groupedProviders={state.groupedProviders}
            onConfigure={state.handleConfigure}
          />
        </SettingsSectionFrame>

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-flags']}
          hidden={activeId !== 'sec-flags'}
          className="[&>div:last-child]:space-y-3"
        >
          <RetrievalEnhancementSection state={state} />
          <FeatureFlagsSection
            getFeatureValue={state.getFeatureValue}
            toggleFeature={state.toggleFeature}
          />
        </SettingsSectionFrame>

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-frontend']}
          hidden={activeId !== 'sec-frontend'}
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
            hidden={activeId !== 'sec-navigation'}
          >
            <NavigationVisibilitySection navigation={state.navigationMerged} updateNavigation={state.updateNavigation} />
          </SettingsSectionFrame>
        ) : null}

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-parsers']}
          hidden={activeId !== 'sec-parsers'}
          className="[&>div:last-child]:space-y-4"
        >
          <ParserServicesSection
            mineru={state.mineruMerged}
            etl4llm={state.etl4llmMerged}
            marker={state.markerMerged}
            docling={state.doclingMerged}
            paddleVl={state.paddleVlMerged}
            textIn={state.textInMerged}
            magicPdf={state.magicPdfMerged}
            updateMinerU={state.updateMinerU}
            updateEtl4Llm={state.updateEtl4Llm}
            updateMarker={state.updateMarker}
            updateDocling={state.updateDocling}
            updatePaddleVL={state.updatePaddleVL}
            updateTextIn={state.updateTextIn}
            updateMagicPDF={state.updateMagicPDF}
          />
        </SettingsSectionFrame>

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-rag']}
          hidden={activeId !== 'sec-rag'}
        >
          <RagSection rag={state.ragMerged} updateRag={state.updateRag} />
        </SettingsSectionFrame>

        {isAdmin ? (
          <SettingsSectionFrame
            section={SETTINGS_SECTION_BY_ID['sec-dify']}
            hidden={activeId !== 'sec-dify'}
          >
            <DifyIntegrationSection
              difyExternalKnowledge={state.difyExternalKnowledgeMerged}
              updateDifyExternalKnowledge={state.updateDifyExternalKnowledge}
            />
          </SettingsSectionFrame>
        ) : null}

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-governance']}
          hidden={activeId !== 'sec-governance'}
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
          hidden={activeId !== 'sec-industry-rules'}
        >
          <IndustryRulesSection />
        </SettingsSectionFrame>

        {isAdmin ? (
          <SettingsSectionFrame
            section={SETTINGS_SECTION_BY_ID['sec-observability']}
            hidden={activeId !== 'sec-observability'}
          >
            <ObservabilitySection
              observability={state.observabilityMerged}
              updateObservability={state.updateObservability}
            />
          </SettingsSectionFrame>
        ) : null}

        <SettingsSectionFrame
          section={SETTINGS_SECTION_BY_ID['sec-runtime']}
          hidden={activeId !== 'sec-runtime'}
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
          </>}
        </div>
      </div>
    </div>
  )
}
