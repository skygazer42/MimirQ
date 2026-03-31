/**
 * 设置页面 - 系统配置管理
 */
'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { AppFrame } from '@/components/app-frame'
import { ModelConfigDialog } from '@/components/model-config-dialog'
import { Button } from '@/components/ui/button'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { FeatureFlagsSection } from './_sections/feature-flags-section'
import { FrontendPreferencesSection } from './_sections/frontend-preferences-section'
import { GovernanceSection } from './_sections/governance-section'
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
  { id: 'sec-observability', label: '可观测性' },
  { id: 'sec-runtime', label: '运行时控制' },
] as const

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
  const state = useSettingsPageState()
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()

  return (
    <AppFrame>
      <PageScaffold
        title="设置与配置"
        badge="SETTINGS"
        icon={Settings2}
        iconColor="text-muted-foreground"
        description="管理功能开关、模型接入及系统参数"
        top={
          state.loadError || state.saveMessage ? (
            <div className="space-y-3">
              {state.loadError ? (
                <Alert variant="destructive" className="shadow-soft/40">
                  <XCircle className="h-4 w-4" />
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
                  className="shadow-soft/40"
                >
                  {state.saveMessage.type === 'success' ? (
                    <CheckCircle2 className="h-4 w-4" />
                  ) : (
                    <XCircle className="h-4 w-4" />
                  )}
                  <div>
                    <AlertTitle>
                      {state.saveMessage.type === 'success' ? '保存成功' : '保存失败'}
                    </AlertTitle>
                    <AlertDescription className="text-foreground/80 space-y-2">
                      <div>{state.saveMessage.text}</div>
                      {state.saveMessage.type === 'success' && state.lastUpdatedKeys.length > 0 ? (
                        <div className="text-xs text-muted-foreground">
                          Updated: {state.lastUpdatedKeys.slice(0, 10).join(', ')}
                          {state.lastUpdatedKeys.length > 10 ? ` (+${state.lastUpdatedKeys.length - 10})` : ''}
                        </div>
                      ) : null}
                    </AlertDescription>
                  </div>
                </Alert>
              ) : null}
            </div>
          ) : null
        }
        actions={
          <>
            <Button
              variant="outline"
              onClick={state.refreshAll}
              disabled={state.loading}
              className="gap-2"
            >
              <RefreshCw className={cn('h-4 w-4', state.loading && 'animate-spin motion-reduce:animate-none')} />
              刷新
            </Button>
            <Button
              onClick={state.saveSettings}
              disabled={!state.hasChanges || state.saving}
              className="gap-2"
            >
              <Save className={cn('h-4 w-4', state.saving && 'animate-pulse motion-reduce:animate-none')} />
              {state.saving ? '保存中...' : '保存配置'}
            </Button>
          </>
        }
      >
        {state.loading ? (
          <div className="flex h-64 items-center justify-center">
            <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground motion-reduce:animate-none" />
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
    <div className="flex gap-8">
      <nav className="hidden lg:block w-44 shrink-0 sticky top-0 self-start pt-1">
        <ul className="space-y-0.5">
          {SETTINGS_SECTIONS.map((sec) => (
            <li key={sec.id}>
              <button
                type="button"
                onClick={() => scrollTo(sec.id)}
                className={cn(
                  'w-full text-left text-xs px-3 py-1.5 rounded-md transition-colors truncate',
                  activeId === sec.id
                    ? 'bg-primary/10 text-primary font-semibold'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
                )}
              >
                {sec.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <div className="flex-1 min-w-0 space-y-12">
        <div id="sec-frontend">
          <FrontendPreferencesSection
            parserBackend={parserBackend}
            setParserBackend={setParserBackend}
            chunkStrategy={chunkStrategy}
            setChunkStrategy={setChunkStrategy}
          />
        </div>

        <div id="sec-flags">
          <FeatureFlagsSection
            editedFeatureFlags={state.editedFeatureFlags}
            getFeatureValue={state.getFeatureValue}
            toggleFeature={state.toggleFeature}
          />
        </div>

        <div id="sec-parsers">
          <ParserServicesSection
            etl4llm={state.etl4llmMerged}
            marker={state.markerMerged}
            paddleVl={state.paddleVlMerged}
            magicPdf={state.magicPdfMerged}
            updateEtl4Llm={state.updateEtl4Llm}
            updateMarker={state.updateMarker}
            updatePaddleVL={state.updatePaddleVL}
            updateMagicPDF={state.updateMagicPDF}
          />
        </div>

        <div id="sec-status">
          {state.status ? (
            <SystemStatusSection status={state.status} backendMeta={state.backendMeta} />
          ) : null}
        </div>

        <div id="sec-models">
          <ModelProvidersSection
            groupedProviders={state.groupedProviders}
            onConfigure={state.handleConfigure}
          />
        </div>

        <div id="sec-ltr">
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

        <div id="sec-rag">
          <RagSection rag={state.ragMerged} updateRag={state.updateRag} />
        </div>

        <div id="sec-url">
          <UrlIngestSection
            urlIngest={state.urlIngestMerged}
            updateUrlIngest={state.updateUrlIngest}
          />
        </div>

        <div id="sec-governance">
          <GovernanceSection
            isGovernanceEnabled={state.isGovernanceEnabled}
            isPiiAnonymizeEnabled={state.isPiiAnonymizeEnabled}
            isSecretsRedactEnabled={state.isSecretsRedactEnabled}
            isQuarantineOnDropEnabled={state.isQuarantineOnDropEnabled}
            updateGovernance={state.updateGovernance}
          />
        </div>

        <div id="sec-observability">
          <ObservabilitySection
            observability={state.observabilityMerged}
            updateObservability={state.updateObservability}
          />
        </div>

        <div id="sec-runtime">
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
