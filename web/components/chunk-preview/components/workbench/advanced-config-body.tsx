'use client'

import { useState, type ReactNode } from 'react'
import { AlertCircle, ArrowUpRight, ChevronDown, Clock, Database, History, Settings2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { ChunkPresetPanel } from '@/components/chunk-preview/components/chunk-preset-panel'
import { ChunkAutoTuneDialog } from '@/components/chunk-preview/components/chunk-auto-tune-dialog'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { toast } from 'sonner'
import { CompareParameters } from './compare-controls'
import styles from './config-dialog.module.css'

function PreviewOptions() {
  const { autoPreviewEnabled, toggleAutoPreview, includeOriginalText, originalTextMaxChars, maxChunks, useParseCache, updatePerfSettings } = useChunkPreview()
  return <details className={styles.disclosure}>
    <summary><span><Settings2 />预览设置</span><ChevronDown /></summary>
    <div className={styles.disclosureBody}>
      <label className={styles.optionRow}><span>自动预览<small>切换文档后生成预览</small></span><Switch aria-label="自动预览" checked={autoPreviewEnabled} onCheckedChange={toggleAutoPreview} /></label>
      <label className={styles.optionRow}><span>返回原文<small>用于核对切块位置</small></span><Switch aria-label="返回原文" checked={includeOriginalText} onCheckedChange={checked => updatePerfSettings({ includeOriginalText: checked })} /></label>
      <label className={styles.optionRow}><span>解析缓存<small>复用同一文档的解析结果</small></span><Switch aria-label="解析缓存" checked={useParseCache} onCheckedChange={checked => updatePerfSettings({ useParseCache: checked })} /></label>
      <div className={styles.limits}>
        <label>原文上限<Input aria-label="原文上限" type="number" min={0} max={2000000} step={10000} value={originalTextMaxChars} disabled={!includeOriginalText} onChange={event => updatePerfSettings({ originalTextMaxChars: Number(event.target.value) })} /></label>
        <label>最多返回切块<Input aria-label="最多返回切块" type="number" min={0} max={20000} step={100} value={maxChunks} onChange={event => updatePerfSettings({ maxChunks: Number(event.target.value) })} /></label>
      </div>
      <p className={styles.note}>上限设为 0 时不限制返回数量。</p>
    </div>
  </details>
}

export function AdvancedConfigBody({ pluginSettings, strategySettings, analysisDetails }: Readonly<{
  pluginSettings: ReactNode
  strategySettings: ReactNode
  analysisDetails: ReactNode
}>) {
  const { previewData, lastPreviewAt, lastPreviewDurationMs, runHistory, clearRunHistory, setParserBackend, updateSettings, isLoading, isSubmitting, chunkStrategy, focusGapReview } = useChunkPreview()
  const [mobileView, setMobileView] = useState<'settings' | 'result'>('settings')
  const stats = previewData?.stats
  const unit = previewData?.params?.unit === 'tokens' ? 'Token' : '字符'
  const coverage = stats?.coverage_ratio == null ? '—' : `${Math.round(stats.coverage_ratio * 100)}%`
  const waste = stats?.overlap_waste_ratio == null ? '—' : `${Math.round(stats.overlap_waste_ratio * 100)}%`
  const at = lastPreviewAt ? new Date(lastPreviewAt).toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : null
  return <div className={styles.body} data-config-workbench data-config-view={mobileView}>
    <fieldset className={styles.presetFieldset} disabled={isLoading || isSubmitting}><ChunkPresetPanel /></fieldset>
    <div className={styles.mobileTabs} role="group" aria-label="高级配置视图"><button type="button" aria-pressed={mobileView === 'settings'} onClick={() => setMobileView('settings')}>参数设置</button><button type="button" aria-pressed={mobileView === 'result'} onClick={() => setMobileView('result')}>上次预览</button></div>
    <div className={styles.columns}>
      <div className={styles.editor} data-config-editor>
        <fieldset className={styles.fields} disabled={isLoading || isSubmitting}>
          <section className={styles.basic}><h2>切块参数</h2><CompareParameters variant="form" /></section>
          <section className={styles.pipeline}><h2><Database />入库管线</h2><PipelineOptionsPanel compact layout="form" /></section>
          <details className={styles.disclosure}><summary><span><Settings2 />管线插件</span><ChevronDown /></summary><div className={styles.disclosureBody}>{pluginSettings}</div></details>
          <PreviewOptions />
          <details className={styles.disclosure}><summary><span>快速调整</span><ChevronDown /></summary><div className={styles.disclosureBody}><div className={styles.quickPresets}>{[
            { label: '通用', strategy: 'auto', chunkSize: 1000, chunkOverlap: 200 },
            { label: '问答', strategy: 'qa_pairs', chunkSize: 800, chunkOverlap: 120 },
            { label: '代码', strategy: 'smart_code', chunkSize: 1000, chunkOverlap: 150 },
            { label: '条款', strategy: 'laws_structured', chunkSize: 1200, chunkOverlap: 200 },
          ].map(item => <Button key={item.strategy} variant="outline" aria-pressed={chunkStrategy === item.strategy} onClick={() => { updateSettings(item); toast.success(`已应用${item.label}参数`) }}>{item.label}</Button>)}</div></div></details>
          {strategySettings}
        </fieldset>
      </div>
      <aside className={styles.results} data-config-results>
        <header className={styles.resultHeading}><h2>上次预览</h2><Clock /></header>
        {previewData ? <>
          <p className={styles.timestamp}>{at || '当前文档'}{lastPreviewDurationMs != null && ` · ${lastPreviewDurationMs} ms`}</p>
          <div className={styles.total}><strong>{previewData.total_chunks_full ?? previewData.total_chunks}</strong><span>个切块</span></div>
          <p className={styles.previewParams}>{getChunkStrategyLabel(previewData.chunk_strategy || 'auto')} · {previewData.params.chunk_size} / {previewData.params.chunk_overlap} {unit}</p>
          <dl className={styles.stats}>
            <div><dt>平均长度</dt><dd>{stats?.avg ?? '—'}<small>{unit}</small></dd></div>
            <div><dt>P95 长度</dt><dd>{stats?.p95 ?? '—'}<small>{unit}</small></dd></div>
            <div><dt>原文覆盖率</dt><dd>{coverage}</dd></div>
            <div><dt>重叠浪费</dt><dd>{waste}</dd></div>
            <div className={stats?.gap_count ? styles.warning : undefined}><dt>断点</dt><dd>{stats?.gap_count ?? '—'}{stats?.largest_gap != null && <small>最大 {stats.largest_gap} {unit}</small>}</dd></div>
          </dl>
          {stats?.gap_count ? <><p className={styles.note}><AlertCircle />可在原文对照中检查断点。</p><button type="button" className={styles.inspectGap} onClick={focusGapReview}>查看断点<ArrowUpRight /></button></> : null}
          {previewData.chunks_truncated && <p className={styles.note}>当前仅返回前 {previewData.total_chunks} 个切块。</p>}
          <details className={styles.disclosure}><summary><span>质量详情与建议</span><ChevronDown /></summary><div className={styles.disclosureBody}><fieldset className={styles.fields} disabled={isLoading || isSubmitting}>{analysisDetails}<ChunkAutoTuneDialog /></fieldset></div></details>
        </> : <p className={styles.noPreview}>生成预览后，这里会显示当前文档的切分统计。</p>}
        <details className={styles.disclosure}><summary><span><History />预览记录{runHistory.length ? ` · ${runHistory.length}` : ''}</span><ChevronDown /></summary><div className={styles.disclosureBody}>
          {runHistory.length ? <><Button variant="ghost" className={styles.clearHistory} onClick={() => { clearRunHistory(); toast.success('已清空预览记录') }}>清空记录</Button><ol className={styles.history}>{runHistory.map(item => <li key={item.id}><button type="button" disabled={isLoading || isSubmitting} onClick={() => { setParserBackend(item.parserBackend); updateSettings({ strategy: item.strategy, chunkSize: item.chunkSize, chunkOverlap: item.chunkOverlap }); toast.info('已载入历史参数，可以生成预览') }}><strong>{item.fileName}</strong><span>{item.totalChunks} 块 · {item.durationMs} ms</span><span>{new Date(item.createdAt).toLocaleString()} · {getChunkStrategyLabel(item.strategy)}</span></button></li>)}</ol></> : <p className={styles.note}>暂无预览记录</p>}
        </div></details>
      </aside>
    </div>
  </div>
}
