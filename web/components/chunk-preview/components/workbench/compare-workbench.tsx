'use client'

import { useEffect, useRef, useState } from 'react'
import { Chunking, FolderOpen, HelpCircle, Upload } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Loader2, Play, Settings2, X } from '@/components/icons'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { ChunkingHelpDialog } from '@/components/chunk-preview/components/chunking-help-dialog'
import { UPLOAD_ACCEPT } from '@/lib/upload-extensions'
import { TopBar } from './top-bar'
import { Sidebar } from './sidebar'
import { OriginalPreview } from './preview/original-preview'
import { ChunkList } from './preview/chunk-list'
import { CompareFooter, CompareParameters } from './compare-controls'
import styles from './compare.module.css'
import configStyles from './config-dialog.module.css'

export function Workbench() {
  const { currentFile, currentFileItem, showOriginalPanel, showSettingsPanel, toggleSettingsPanel, setOriginalPanelVisible, isDragging, handleDragOver, handleDragLeave, handleDrop, addFiles, loadExample, isLoading, isSubmitting, runPreview, cancelPreview, gapReviewRequest } = useChunkPreview()
  const lastGapFocus = useRef(gapReviewRequest)
  const [documentsOpen, setDocumentsOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [mobileView, setMobileView] = useState<'original' | 'chunks'>('chunks')
  useEffect(() => { if (!showOriginalPanel) setMobileView('chunks') }, [showOriginalPanel])
  useEffect(() => { if (gapReviewRequest > 0) setMobileView('chunks') }, [gapReviewRequest])
  const openDocuments = () => { if (showSettingsPanel) toggleSettingsPanel(); setDocumentsOpen(true) }
  const openSettings = () => { setDocumentsOpen(false); if (!showSettingsPanel) toggleSettingsPanel() }
  const closePanel = () => { setDocumentsOpen(false); if (showSettingsPanel) toggleSettingsPanel() }
  const ready = Boolean(currentFile && currentFileItem)
  return <div className={styles.page} data-chunk-compare-page data-mobile-view={mobileView}>
    {ready ? <TopBar onOpenDocuments={openDocuments} /> : <header className={styles.header}><div className={styles.title}><PageTitleIcon name="chunk-preview" /><div><h1>切块预览</h1><p>检查切分结果与原文位置</p></div></div><div className={styles.headerActions}><Button variant="outline" onClick={openDocuments}><FolderOpen />管理文档</Button></div></header>}
    <CompareParameters />
    {ready ? <>
      <div className={styles.mobileViews} role="group" aria-label="切块预览视图"><button type="button" aria-pressed={mobileView === 'original'} onClick={() => { setOriginalPanelVisible(true); setMobileView('original') }}>文档原文</button><button type="button" aria-pressed={mobileView === 'chunks'} onClick={() => setMobileView('chunks')}>切块结果</button></div>
      <div className={styles.workspace} data-original-visible={showOriginalPanel}>
        {showOriginalPanel && <section className={styles.original} aria-label="文档原文" data-compare-original><OriginalPreview /></section>}
        <section className={styles.results} aria-label="切块结果" data-compare-results><ChunkList mobileView={mobileView} /></section>
      </div>
    </> : <div className={styles.empty} data-chunk-preview-empty-canvas data-dragging={isDragging} onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}>
      <Chunking appearance="color" className="icon-ink-process" /><h2>{isDragging ? '松开鼠标上传文档' : '选择文档，查看切块结果'}</h2><p>可以使用已解析的文档，也可以上传文件预览切分效果。</p>
      <div className={styles.emptyActions}><Button onClick={openDocuments}><FolderOpen />选择已有文档</Button><Button variant="outline" onClick={() => document.getElementById('chunk-empty-file-input')?.click()}><Upload />上传文件</Button><Button variant="ghost" onClick={loadExample}>试用示例文档</Button></div>
      <input id="chunk-empty-file-input" aria-label="上传切块预览文档" type="file" accept={UPLOAD_ACCEPT} multiple hidden onChange={event => { const files = Array.from(event.target.files || []); if (files.length > 0) addFiles(files); event.target.value = '' }} />
      <button type="button" className={styles.emptyHelp} onClick={() => setHelpOpen(true)}><HelpCircle />切块指南</button>
    </div>}
    <CompareFooter onOpenDocuments={openDocuments} />
    <Sheet open={documentsOpen} onOpenChange={open => { if (!open) setDocumentsOpen(false) }}><SheetContent className={styles.drawer}>
      <SheetHeader className={styles.drawerHeader}><SheetTitle>文档与数据范围</SheetTitle><SheetDescription>选择要预览的文档，或管理本次处理的文件</SheetDescription></SheetHeader>
      <div className={styles.drawerTabs} role="group" aria-label="切块配置面板"><button type="button" aria-pressed={true}>文档与范围</button><button type="button" aria-pressed={false} onClick={openSettings}>高级配置</button></div>
      <Sidebar variant="dialog" section="documents" />
      <div className={styles.drawerDone}><Button variant="outline" onClick={closePanel}>返回预览</Button></div>
    </SheetContent></Sheet>
    <Dialog open={showSettingsPanel} onOpenChange={open => { if (open !== showSettingsPanel) toggleSettingsPanel() }}><DialogContent className={configStyles.dialog} onCloseAutoFocus={event => { event.preventDefault(); const gapNavigation = gapReviewRequest > lastGapFocus.current; lastGapFocus.current = gapReviewRequest; document.querySelector<HTMLElement>(gapNavigation ? '[data-compare-results] [data-page-scroll-container]' : '[aria-label="打开高级切块配置"]')?.focus() }}>
      <DialogHeader className={configStyles.header}><DialogTitle><Settings2 />高级切块配置</DialogTitle><DialogDescription><FileTypeIcon type={currentFileItem?.originalFileType} filename={currentFileItem?.displayName || currentFile?.name} />{currentFileItem?.displayName || currentFile?.name || '选择文档后生成预览'}</DialogDescription></DialogHeader>
      <Sidebar variant="dialog" section="settings" />
      <footer className={configStyles.footer}><Button variant="outline" onClick={closePanel}>返回预览</Button><Button className={configStyles.primary} disabled={!currentFile || isSubmitting} onClick={() => { if (isLoading) cancelPreview(); else void runPreview({ force: true }) }}>{isLoading ? <X /> : isSubmitting ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Play />}{isLoading ? '取消预览' : '生成预览'}</Button></footer>
    </DialogContent></Dialog>
    <ChunkingHelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
  </div>
}
