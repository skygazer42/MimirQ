'use client'

import { useState } from 'react'
import { FileText, Loader2, Paperclip, Play } from '@/components/icons'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import styles from './parsing-compare.module.css'
import { useTranslations } from 'next-intl'

import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { ParsingRightPanel } from '@/components/parsing/parsing-right-panel'
import { Button } from '@/components/ui/button'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import type { ParsedFileData } from '@/store/use-parsed-files-store'

type StatusBadge = {
 label: string
 cls: string
}

type ParsingLibraryPreviewPaneProps = {
 file: ParsedFileData
 activeMarkdown: string
 folderName: string
 folderPathLabel: string
 sourceStatus: 'unknown' | 'available' | 'missing'
 defaultParserBackend: string
 statusBadge?: StatusBadge | null
 onClose: () => void
 onUpdateParser: (backend: string) => void
 onReprocessKnowledgeFile: (backend: string) => void
 onRestoreSource: (autoParse: boolean) => void
 onRequestRebind: (autoParse: boolean) => void
}

export function ParsingLibraryPreviewPane({
 file,
 activeMarkdown,
 sourceStatus,
 defaultParserBackend,
 onUpdateParser,
 onReprocessKnowledgeFile,
 onRestoreSource,
 onRequestRebind,
}: Readonly<ParsingLibraryPreviewPaneProps>) {
 const t = useTranslations('ParsingWorkbench')
 const [narrowView, setNarrowView] = useState<'source' | 'result'>('result')
 const parserValue = resolveParserBackendForFilename(
 file.filename,
 file.parserBackend || defaultParserBackend
 ).backend
 const isKnowledgeBaseFile = file.source === 'knowledge_base'
 const canRunLibraryParse = Boolean(file.status && file.status !== 'parsed' && file.status !== 'parsing')
 const pendingParseAction = (() => {
 if (!canRunLibraryParse) return null
 if (isKnowledgeBaseFile) {
 return {
 label: t('libraryPreview.startParsing'),
 title: t('libraryPreview.startParsingTitle'),
 onClick: () => onReprocessKnowledgeFile(parserValue),
 }
 }
 if (sourceStatus === 'available') {
 return {
 label: t('libraryPreview.continueParsing'),
 title: t('libraryPreview.continueParsingTitle'),
 onClick: () => onRestoreSource(true),
 }
 }
 return {
 label: t('libraryPreview.uploadAndParse'),
 title: t('libraryPreview.uploadAndParseTitle'),
 onClick: () => onRequestRebind(true),
 }
 })()
 const sourceAction = sourceStatus === 'available'
 ? {
 label: t('libraryPreview.restoreSource'),
 title: t('libraryPreview.restoreSourceTitle'),
 onClick: () => onRestoreSource(false),
 }
 : {
 label: t('libraryPreview.reupload'),
 title: t('libraryPreview.reuploadTitle'),
 onClick: () => onRequestRebind(false),
 }

 return <>
   <div className={styles.mobileTabs} role="group" aria-label="核对视图">
     <span className={styles.mobileIndicator} style={{ transform: narrowView === 'source' ? 'translateX(0)' : 'translateX(100%)' }} />
     <button type="button" aria-pressed={narrowView === 'source'} onClick={() => setNarrowView('source')}>原文</button>
     <button type="button" aria-pressed={narrowView === 'result'} onClick={() => setNarrowView('result')}>解析结果</button>
   </div>
   <div className={styles.workspace} data-narrow-view={narrowView}>
     <section className={styles.source} aria-label="原文">
       <div className={styles.resultToolbar}><FileText className="size-3.5 text-muted-foreground" /><span className="text-[13px]">原始文件</span></div>
       <div className={styles.empty}>
         <FileTypeIcon filename={file.filename} className="size-10" />
         <h2>{sourceStatus === 'unknown' ? '正在检查原文件' : sourceStatus === 'missing' ? '原文件暂不可用' : '打开原文件'}</h2>
         <p>{sourceStatus === 'missing' ? '重新关联原文件后，可以并排核对解析结果。' : '解析内容已保留，打开原文件即可对照查看。'}</p>
         {sourceStatus === 'unknown' ? <Loader2 className="size-5 animate-spin motion-reduce:animate-none" /> : <Button size="sm" variant="outline" onClick={sourceAction.onClick} className="gap-2"><Paperclip className="size-4" />{sourceAction.label}</Button>}
       </div>
     </section>
     <section className={styles.result} aria-label="解析结果">
       <div className={styles.resultToolbar}><span className="text-[13px]">Markdown</span><span className="ml-auto text-xs text-muted-foreground">{file.parser || getParserLabel(parserValue)}</span></div>
       {activeMarkdown ? <ParsingRightPanel className={styles.markdownBody}><article className={styles.markdown}><MarkdownRenderer markdown={activeMarkdown} /></article></ParsingRightPanel> : <div className={styles.resultState}>
         {file.status === 'parsing' ? <><Loader2 className="size-7 animate-spin text-info motion-reduce:animate-none" /><h2>正在解析</h2><p>解析完成后将在此显示结果。</p></> : <><FileText className="size-7 text-muted-foreground" /><h2>{file.status === 'error' ? '解析失败' : '文档待解析'}</h2><p>{file.error || '选择解析器，提取文档内容。'}</p>
           {canRunLibraryParse ? <div className={styles.startParser}><ParserDropdown value={parserValue} filename={file.filename} onChange={onUpdateParser} /></div> : null}
           {pendingParseAction ? <Button size="sm" className="gap-2" onClick={pendingParseAction.onClick}><Play className="size-4" />{pendingParseAction.label}</Button> : null}
         </>}
       </div>}
     </section>
   </div>
   <footer className={styles.footer}><span>{activeMarkdown ? activeMarkdown.length.toLocaleString() + ' 字符' : '等待解析结果'}</span>
     <Button size="sm" variant="outline" className="gap-2" onClick={sourceAction.onClick}><Paperclip className="size-4" />{sourceAction.label}</Button>
   </footer>
 </>
}
