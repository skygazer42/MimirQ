'use client'

import { useEffect, useState } from 'react'
import { AlertCircle, ChevronDown, Loader2, Play, Settings2, X } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ChunkStrategyDropdown } from '@/components/business/chunk-strategy-dropdown'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { applyChunkOverridesToPreview } from '@/components/chunk-preview/utils/export'
import { chunkNeedsReview, isChunkOverrideDisabled } from '@/components/chunk-preview/utils/metadata'
import styles from './compare.module.css'

export function CompareParameters({ variant = 'toolbar' }: Readonly<{ variant?: 'toolbar' | 'form' }> = {}) {
  const { chunkStrategy, chunkSize, chunkOverlap, currentFile, isLoading, isSubmitting, updateSettings, runPreview, cancelPreview, toggleSettingsPanel } = useChunkPreview()
  const [sizeDraft, setSizeDraft] = useState(String(chunkSize))
  const [overlapDraft, setOverlapDraft] = useState(String(chunkOverlap))
  const [expanded, setExpanded] = useState(false)
  useEffect(() => setSizeDraft(String(chunkSize)), [chunkSize])
  useEffect(() => setOverlapDraft(String(chunkOverlap)), [chunkOverlap])
  const tokenBased = chunkStrategy === 'langchain_token'
  const sizeMin = tokenBased ? 50 : 100
  const sizeMax = tokenBased ? 2000 : 4000
  const overlapMax = Math.min(tokenBased ? 500 : 1000, Math.max(0, chunkSize - sizeMin))
  const unit = tokenBased ? 'Token' : '字符'
  const setSize = (raw: string, commit = false) => {
    setSizeDraft(raw)
    const parsed = Number(raw)
    if (!raw.trim() || !Number.isFinite(parsed)) { if (commit) setSizeDraft(String(chunkSize)); return }
    if (!commit && (!Number.isInteger(parsed) || parsed < sizeMin || parsed > sizeMax)) return
    const next = Math.max(sizeMin, Math.min(sizeMax, Math.trunc(parsed)))
    updateSettings({ chunkSize: next, chunkOverlap: Math.min(chunkOverlap, Math.min(tokenBased ? 500 : 1000, Math.max(0, next - sizeMin))) })
    if (commit) setSizeDraft(String(next))
  }
  const setOverlap = (raw: string, commit = false) => {
    setOverlapDraft(raw)
    const parsed = Number(raw)
    if (!raw.trim() || !Number.isFinite(parsed)) { if (commit) setOverlapDraft(String(chunkOverlap)); return }
    if (!commit && (!Number.isInteger(parsed) || parsed < 0 || parsed > overlapMax)) return
    const next = Math.max(0, Math.min(overlapMax, Math.trunc(parsed)))
    updateSettings({ chunkOverlap: next })
    if (commit) setOverlapDraft(String(next))
  }
  return <div className={variant === 'form' ? styles.formParameters : styles.parameters} aria-label="常用切块参数" data-compare-parameters data-expanded={expanded}>
    {variant === 'toolbar' && <button type="button" className={styles.parameterSummary} aria-expanded={expanded} onClick={() => setExpanded(value => !value)}><span>切块参数</span><span className={styles.metadata}>{chunkSize} / {chunkOverlap} {unit}</span><ChevronDown /></button>}
    <fieldset className="contents" disabled={isLoading || isSubmitting}>
      <div className={`${styles.parameter} ${styles.strategy}`}><span>切块策略</span><ChunkStrategyDropdown compact disabled={isLoading || isSubmitting} value={chunkStrategy} onChange={strategy => updateSettings({ strategy })} /></div>
      <label className={styles.parameter}><span>目标长度</span><span className={styles.numberInput}><Input aria-label={`目标长度（${unit}）`} type="number" min={sizeMin} max={sizeMax} step={1} value={sizeDraft} onChange={event => setSize(event.target.value)} onBlur={event => setSize(event.target.value, true)} /><small>{unit}</small></span></label>
      <label className={styles.parameter}><span>重叠长度</span><span className={styles.numberInput}><Input aria-label={`重叠长度（${unit}）`} type="number" min={0} max={overlapMax} step={1} value={overlapDraft} disabled={chunkStrategy === 'separator'} onChange={event => setOverlap(event.target.value)} onBlur={event => setOverlap(event.target.value, true)} /><small>{unit}</small></span></label>
    </fieldset>
    {variant === 'toolbar' && <div className={styles.parameterActions}>
      <Button variant="ghost" disabled={isSubmitting || isLoading} onClick={toggleSettingsPanel} aria-label="打开高级切块配置"><Settings2 />更多参数</Button>
      <Button variant="outline" disabled={!currentFile || isSubmitting} onClick={() => isLoading ? cancelPreview() : void runPreview({ force: true })}>{isLoading ? <X /> : isSubmitting ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Play />}{isLoading ? '取消预览' : '生成预览'}</Button>
    </div>}
  </div>
}

export function CompareFooter({ onOpenDocuments }: Readonly<{ onOpenDocuments: () => void }>) {
  const { previewData, chunkOverrides, selectedChunkIndex, datasetId, currentFileItem, isLoading } = useChunkPreview()
  const effective = previewData ? applyChunkOverridesToPreview(previewData, chunkOverrides, { include_disabled: true }) : null
  const reviewCount = effective?.chunks.filter((chunk,index) => !isChunkOverrideDisabled(chunkOverrides[index]) && chunkNeedsReview(chunk)).length || 0
  const disabledCount = Object.values(chunkOverrides).filter(isChunkOverrideDisabled).length
  const scope = datasetId ? currentFileItem?.datasetName || '已选数据集' : '解析工作区'
  return <footer className={styles.footer}>
    <span>{isLoading ? '正在生成预览…' : previewData ? `${previewData.total_chunks_full ?? previewData.total_chunks} 个切块` : '尚未生成预览'}</span>
    {!!reviewCount && <span className={styles.reviewCount}><AlertCircle />{reviewCount} 项待复核</span>}
    {!!disabledCount && <span>{disabledCount} 项已跳过</span>}
    {selectedChunkIndex !== null && <span className="hidden md:inline">当前第 {selectedChunkIndex + 1} 块</span>}
    <div className={styles.footerScope}><span>数据范围</span><Button variant="outline" onClick={onOpenDocuments} aria-label={`选择数据范围，当前${scope}`}><span>{scope}</span><ChevronDown /></Button></div>
  </footer>
}
