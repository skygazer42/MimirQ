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
import { StickyActionRail } from '@/components/ui/sticky-action-rail'
import { SystemDataStrip } from '@/components/ui/system-data-strip'
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
  RefreshCw,
  Save,
  Settings2,
  XCircle,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import { systemDenseControls, systemPageTokens } from '@/components/ui/system-page-tokens'

const SETTINGS_SECTIONS = [
  { id: 'sec-frontend', label: '前端偏好' },
  { id: 'sec-flags', label: '功能开关' },
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
const DENSE_OUTLINE_BUTTON = systemDenseControls.outlineButton
const DENSE_PRIMARY_BUTTON = systemDenseControls.primaryButton

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
      },
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
    <TenantPermissionGate permission={TENANT_PERMISSIONS.SETTINGS_READ} pageName="系统设置">
      <SettingsPageContent />
    </TenantPermissionGate>
  )
}

function SettingsPageContent() {
  const state = useSettingsPageState()
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const statusStripItems = [
    { label: '配置分区', value: SETTINGS_SECTIONS.length, mono: true },
    {
      label: '草稿变更',
      value: state.hasChanges ? '待保存' : '已同步',
      tone: state.hasChanges ? 'warning' : 'success',
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
      tone:
        state.saveMessage?.type === 'error'
          ? 'danger'
          : state.saving
            ? 'warning'
            : state.saveMessage?.type === 'success'
              ? 'success'
              : 'default',
    },
    { label: '最近更新键', value: state.lastUpdatedKeys.length, mono: true },
  ] as const

  return (
    <AppFrame>
      <PageScaffold
        title="设置与配置"
        badge="系统配置"
        icon={Settings2}
        iconColor="text-muted-foreground"
        description="统一管理功能开关、模型接入、检索增强生成参数（RAG）与运行时控制。"
        size="full"
        density="system-dense"
        top={
          <div className="space-y-2">
            <SystemDataStrip items={statusStripItems} minColumnWidth={148} />
            {state.loadError ? (
              <Alert variant="destructive" className="rounded-lg border-border/70 shadow-none">
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
                variant={state.saveMessage.type === 'success' ? 'success' : 'destructive'}
                className="rounded-lg border-border/70 shadow-none"
              >
                {state.saveMessage.type === 'success' ? (
                  <CheckCircle2 className="size-4" />
                ) : (
                  <XCircle className="size-4" />
                )}
                <div>
                  <AlertTitle>
                    {state.saveMessage.type === 'success' ? '保存成功' : '保存失败'}
                  </AlertTitle>
                  <AlertDescription className="text-foreground/80 space-y-2">
                    <div>{state.saveMessage.text}</div>
                    {state.saveMessage.type === 'success' && state.lastUpdatedKeys.length > 0 ? (
                      <div className={systemPageTokens.subtle}>
                        已更新：{state.lastUpdatedKeys.slice(0, 10).join(', ')}
                        {state.lastUpdatedKeys.length > 10 ? ` (+${state.lastUpdatedKeys.length - 10})` : ''}
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
              className={DENSE_OUTLINE_BUTTON}
            >
              <RefreshCw className={cn('size-4', state.loading && 'animate-spin motion-reduce:animate-none')} />
              刷新
            </Button>
            <Button
              onClick={state.saveSettings}
              disabled={!state.hasChanges || state.saving}
              className={DENSE_PRIMARY_BUTTON}
            >
              <Save className={cn('size-4', state.saving && 'animate-pulse motion-reduce:animate-none')} />
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
          <SettingsContent state={state} parserBackend={parserBackend} setParserBackend={setParserBackend} chunkStrategy={chunkStrategy} setChunkStrategy={setChunkStrategy} />
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

function SettingsContent({ state, parserBackend, setParserBackend, chunkStrategy, setChunkStrategy }: any) {
  const sectionIds = SETTINGS_SECTIONS.map((s) => s.id)
  const activeId = useSettingsScrollSpy(sectionIds)

  const scrollTo = useCallback((id: string) => {
    const el = document.getElementById(id)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  return (
    <div className="flex gap-4 lg:gap-5">
      <nav className="sticky top-4 hidden w-52 shrink-0 self-start pt-2 lg:flex lg:justify-center">
        <ul className="w-full max-w-[12.5rem] space-y-1.5">
          {SETTINGS_SECTIONS.map((sec) => (
            <li key={sec.id}>
              <button
                type="button"
                onClick={() => scrollTo(sec.id)}
                className={cn(
                  'relative w-full rounded-lg px-3.5 py-2.5 text-center transition-colors',
                  'text-[14px] font-semibold leading-5',
                  activeId === sec.id
                    ? 'bg-primary/10 text-primary before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-[2px] before:rounded-full before:bg-primary'
                    : 'text-muted-foreground hover:bg-muted/40 hover:text-foreground',
                )}
              >
                {sec.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <div className="min-w-0 flex-1 space-y-6">
        <div id="sec-frontend" className="scroll-mt-24">
          <FrontendPreferencesSection
            parserBackend={parserBackend}
            setParserBackend={setParserBackend}
            chunkStrategy={chunkStrategy}
            setChunkStrategy={setChunkStrategy}
          />
        </div>

        <div id="sec-flags" className="scroll-mt-24">
          <FeatureFlagsSection
            editedFeatureFlags={state.editedFeatureFlags}
            getFeatureValue={state.getFeatureValue}
            toggleFeature={state.toggleFeature}
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
            <SystemStatusSection status={state.status} backendMeta={state.backendMeta} />
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

        <StickyActionRail>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className={systemPageTokens.subtle}>
              {state.hasChanges
                ? '存在未保存改动：建议保存后再离开页面。'
                : '当前草稿与后端配置一致。'}
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                onClick={state.refreshAll}
                disabled={state.loading}
                className={DENSE_OUTLINE_BUTTON}
              >
                <RefreshCw className={cn('size-4', state.loading && 'animate-spin motion-reduce:animate-none')} />
                刷新
              </Button>
              <Button
                onClick={state.saveSettings}
                disabled={!state.hasChanges || state.saving}
                className={DENSE_PRIMARY_BUTTON}
              >
                <Save className={cn('size-4', state.saving && 'animate-pulse motion-reduce:animate-none')} />
                {state.saving ? '保存中...' : '保存配置'}
              </Button>
            </div>
          </div>
        </StickyActionRail>
      </div>
    </div>
  )
}
