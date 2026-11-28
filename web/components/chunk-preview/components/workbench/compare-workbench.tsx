'use client'

import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import {
  Check,
  ChevronRight,
  FolderOpen,
  Loader2,
  Play,
  Settings2,
  Upload,
  X,
} from '@/components/icons'
import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { ChunkingHelpDialog } from '@/components/chunk-preview/components/chunking-help-dialog'
import { formatApiError } from '@/lib/api-errors'
import { UPLOAD_ACCEPT } from '@/lib/upload-extensions'
import { TopBar } from './top-bar'
import { Sidebar } from './sidebar'
import { OriginalPreview } from './preview/original-preview'
import { ChunkList } from './preview/chunk-list'
import { CompareFooter, CompareParameters } from './compare-controls'
import styles from './compare.module.css'
import configStyles from './config-dialog.module.css'

const QUICK_CHUNKING_PRESETS = [
  {
    id: 'recursive',
    label: '通用递归切分 · 1000 / 200 字符',
    strategy: 'langchain_recursive',
    chunkSize: 1000,
    chunkOverlap: 200,
  },
  {
    id: 'outline',
    label: '标题层级切分 · 1200 / 150 字符',
    strategy: 'outline',
    chunkSize: 1200,
    chunkOverlap: 150,
  },
  {
    id: 'token',
    label: '精准 Token 切分 · 500 / 100 Token',
    strategy: 'langchain_token',
    chunkSize: 500,
    chunkOverlap: 100,
  },
] as const

export function Workbench() {
  const {
    currentFile,
    currentFileItem,
    chunkStrategy,
    chunkSize,
    chunkOverlap,
    updateSettings,
    showOriginalPanel,
    showSettingsPanel,
    toggleSettingsPanel,
    setOriginalPanelVisible,
    isDragging,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    addFiles,
    loadExample,
    isLoading,
    isSubmitting,
    runPreview,
    cancelPreview,
    gapReviewRequest,
  } = useChunkPreview()
  const lastGapFocus = useRef(gapReviewRequest)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [documentsOpen, setDocumentsOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [mobileView, setMobileView] = useState<'original' | 'chunks'>('chunks')
  useEffect(() => {
    if (!showOriginalPanel) setMobileView('chunks')
  }, [showOriginalPanel])
  useEffect(() => {
    if (gapReviewRequest > 0) setMobileView('chunks')
  }, [gapReviewRequest])
  const openDocuments = () => {
    if (showSettingsPanel) toggleSettingsPanel()
    setDocumentsOpen(true)
  }
  const openSettings = () => {
    setDocumentsOpen(false)
    if (!showSettingsPanel) toggleSettingsPanel()
  }
  const closePanel = () => {
    setDocumentsOpen(false)
    if (showSettingsPanel) toggleSettingsPanel()
  }
  const ready = Boolean(currentFile && currentFileItem)
  const documentName = currentFileItem?.displayName ?? currentFile?.name
  return (
    <div className={styles.page} data-chunk-compare-page data-mobile-view={mobileView}>
      {ready ? (
        <TopBar onOpenDocuments={openDocuments} />
      ) : (
        <header className={styles.header}>
          <div className={styles.title}>
            <PageTitleIcon name="chunk-preview" />
            <h1>切块预览</h1>
          </div>
          <div className={styles.headerActions}>
            <Button variant="outline" onClick={openDocuments} aria-label="管理文档">
              <FolderOpen />
              管理文档
            </Button>
          </div>
        </header>
      )}
      <CompareParameters />
      {ready ? (
        <>
          <div className={styles.mobileViews} role="group" aria-label="切块预览视图">
            <button
              type="button"
              aria-pressed={mobileView === 'original'}
              onClick={() => {
                setOriginalPanelVisible(true)
                setMobileView('original')
              }}
            >
              文档原文
            </button>
            <button type="button" aria-pressed={mobileView === 'chunks'} onClick={() => setMobileView('chunks')}>
              切块结果
            </button>
          </div>
          <div className={styles.workspace} data-original-visible={showOriginalPanel}>
            {showOriginalPanel && (
              <section className={styles.original} aria-label="文档原文" data-compare-original>
                <OriginalPreview />
              </section>
            )}
            <section className={styles.results} aria-label="切块结果" data-compare-results>
              <ChunkList mobileView={mobileView} />
            </section>
          </div>
        </>
      ) : (
        <div
          className={styles.empty}
          data-chunk-preview-empty-canvas
          data-dragging={isDragging}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={(event) => {
            void handleDrop(event).catch((error) => toast.error(formatApiError(error, '无法读取拖入的文件')))
          }}
        >
          <div className={styles.emptySplitStudio} data-chunk-empty-studio="true">
            <section className={styles.emptyIntakeStage} aria-label="文档切片导入">
              <div className={styles.emptyChunkIllust} aria-hidden="true">
                <svg viewBox="0 0 132 146" fill="none">
                  <path
                    d="M18 10C18 6.686 20.686 4 24 4H92L114 26V136C114 139.314 111.314 142 108 142H24C20.686 142 18 139.314 18 136V10Z"
                    fill="hsl(var(--card))"
                    stroke="currentColor"
                    strokeOpacity="0.34"
                    strokeWidth="1.25"
                  />
                  <path d="M92 4V26H114" stroke="currentColor" strokeOpacity="0.28" strokeWidth="1.25" />

                  <rect
                    x="30"
                    y="24"
                    width="72"
                    height="26"
                    rx="4"
                    fill="hsl(var(--surface-2) / 0.7)"
                    stroke="currentColor"
                    strokeOpacity="0.24"
                    strokeWidth="1"
                  />
                  <rect x="38" y="32" width="48" height="3" rx="1.5" fill="currentColor" fillOpacity="0.28" />
                  <rect x="38" y="40" width="34" height="3" rx="1.5" fill="currentColor" fillOpacity="0.2" />

                  <line
                    x1="24"
                    y1="57"
                    x2="108"
                    y2="57"
                    stroke="hsl(var(--accent))"
                    strokeWidth="1.4"
                    strokeDasharray="4 4"
                    strokeLinecap="round"
                  />

                  <rect
                    x="30"
                    y="64"
                    width="72"
                    height="26"
                    rx="4"
                    fill="hsl(var(--surface-2) / 0.7)"
                    stroke="currentColor"
                    strokeOpacity="0.24"
                    strokeWidth="1"
                  />
                  <rect x="38" y="72" width="52" height="3" rx="1.5" fill="currentColor" fillOpacity="0.28" />
                  <rect x="38" y="80" width="38" height="3" rx="1.5" fill="currentColor" fillOpacity="0.2" />

                  <line
                    x1="24"
                    y1="97"
                    x2="108"
                    y2="97"
                    stroke="hsl(var(--accent))"
                    strokeWidth="1.4"
                    strokeDasharray="4 4"
                    strokeLinecap="round"
                  />

                  <rect
                    x="30"
                    y="104"
                    width="72"
                    height="26"
                    rx="4"
                    fill="hsl(var(--surface-2) / 0.7)"
                    stroke="currentColor"
                    strokeOpacity="0.24"
                    strokeWidth="1"
                  />
                  <rect x="38" y="112" width="42" height="3" rx="1.5" fill="currentColor" fillOpacity="0.28" />
                  <rect x="38" y="120" width="50" height="3" rx="1.5" fill="currentColor" fillOpacity="0.2" />
                </svg>
              </div>
              <h2>{isDragging ? '松开鼠标上传文档' : '预览文档切片'}</h2>
              <p>调整切分策略与重叠长度，实时对比分块边界、覆盖率与字符分布。</p>
              <div className={styles.emptyStageActions}>
                <Button className={styles.emptyPrimaryBtn} onClick={openDocuments}>
                  <FolderOpen className="size-4" />
                  选择已有文档
                </Button>
                <Button variant="outline" onClick={() => fileInputRef.current?.click()}>
                  <Upload className="size-4" />
                  上传文件
                </Button>
              </div>
            </section>
            <aside className={styles.emptyGuideStage} aria-label="切分预设与示例">
              <div className={styles.emptyGuideGroup}>
                <h3>推荐切分预设</h3>
                <div className={styles.emptyRowList} role="group" aria-label="快捷切分预设">
                  {QUICK_CHUNKING_PRESETS.map((preset) => {
                    const active =
                      chunkStrategy === preset.strategy &&
                      chunkSize === preset.chunkSize &&
                      chunkOverlap === preset.chunkOverlap
                    return (
                      <button
                        key={preset.id}
                        type="button"
                        className={styles.emptyRowButton}
                        aria-pressed={active}
                        disabled={isLoading || isSubmitting}
                        onClick={() =>
                          updateSettings({
                            strategy: preset.strategy,
                            chunkSize: preset.chunkSize,
                            chunkOverlap: preset.chunkOverlap,
                          })
                        }
                      >
                        <span className={styles.emptyPresetLabel}>{preset.label}</span>
                        {active ? <Check className={styles.emptyPresetCheck} aria-hidden="true" /> : null}
                      </button>
                    )
                  })}
                </div>
              </div>
              <div className={styles.emptyGuideGroup}>
                <h3>示例与帮助</h3>
                <div className={styles.emptyRowList}>
                  <button
                    type="button"
                    className={styles.emptyRowButton}
                    aria-label="打开示例文档"
                    onClick={loadExample}
                  >
                    <span className={styles.emptyActionCopy}>
                      <strong>打开示例文档</strong>
                      <small>载入示例文本预览切块</small>
                    </span>
                    <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className={styles.emptyRowButton}
                    onClick={() => setHelpOpen(true)}
                  >
                    <span className={styles.emptyActionCopy}>
                      <strong>切块指南</strong>
                      <small>查看策略选型与重叠参数建议</small>
                    </span>
                    <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                  </button>
                </div>
              </div>
            </aside>
          </div>
          <input
            id="chunk-empty-file-input"
            ref={fileInputRef}
            aria-label="上传切块预览文档"
            type="file"
            accept={UPLOAD_ACCEPT}
            multiple
            hidden
            onChange={(event) => {
              const input = event.currentTarget
              if (input.files !== null && input.files.length > 0) addFiles(Array.from(input.files))
              input.value = ''
            }}
          />
        </div>
      )}
      <CompareFooter onOpenDocuments={openDocuments} />
      <Sheet
        open={documentsOpen}
        onOpenChange={(open) => {
          if (!open) setDocumentsOpen(false)
        }}
      >
        <SheetContent className={styles.drawer}>
          <SheetHeader className={styles.drawerHeader}>
            <SheetTitle>文档与数据范围</SheetTitle>
            <SheetDescription>按数据集筛选文档，或管理已添加的文件。</SheetDescription>
          </SheetHeader>
          <div className={styles.drawerTabs} role="group" aria-label="切块配置面板">
            <button type="button" aria-pressed={true} disabled>
              文档与范围
            </button>
            <button type="button" aria-pressed={false} onClick={openSettings}>
              高级配置
            </button>
          </div>
          <Sidebar variant="dialog" section="documents" />
          <div className={styles.drawerDone}>
            <Button variant="outline" onClick={closePanel}>
              返回预览
            </Button>
          </div>
        </SheetContent>
      </Sheet>
      <Dialog
        open={showSettingsPanel}
        onOpenChange={(open) => {
          if (open !== showSettingsPanel) toggleSettingsPanel()
        }}
      >
        <DialogContent
          className={configStyles.dialog}
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            const gapNavigation = gapReviewRequest > lastGapFocus.current
            lastGapFocus.current = gapReviewRequest
            document
              .querySelector<HTMLElement>(
                gapNavigation
                  ? '[data-compare-results] [data-page-scroll-container]'
                  : '[aria-label="打开高级切块配置"]',
              )
              ?.focus()
          }}
        >
          <DialogHeader className={configStyles.header}>
            <DialogTitle>
              <Settings2 />
              高级切块配置
            </DialogTitle>
            <DialogDescription>
              <FileTypeIcon type={currentFileItem?.originalFileType} filename={documentName} />
              {documentName ?? '选择文档后生成预览'}
            </DialogDescription>
          </DialogHeader>
          <Sidebar variant="dialog" section="settings" />
          <footer className={configStyles.footer}>
            <Button variant="outline" onClick={closePanel}>
              返回预览
            </Button>
            <Button
              className={configStyles.primary}
              disabled={!currentFile || isSubmitting}
              onClick={() => {
                if (isLoading) cancelPreview()
                else void runPreview({ force: true })
              }}
            >
              {isLoading ? (
                <X />
              ) : isSubmitting ? (
                <Loader2 className="animate-spin motion-reduce:animate-none" />
              ) : (
                <Play />
              )}
              {isLoading ? '取消预览' : '生成预览'}
            </Button>
          </footer>
        </DialogContent>
      </Dialog>
      <ChunkingHelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
    </div>
  )
}
