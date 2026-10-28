'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ChevronRight,
  Hash,
  Highlighter,
  Loader2,
  Shield,
  Tag,
  Type,
  X,
} from '@/components/icons'
import styles from './governance-inbox.module.css'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { pipelineApi } from '@/lib/api'
import { reportClientWarning } from '@/lib/client-logging'
import type { AutoAnnotationRequest, AutoDocumentTag } from '@/types'

export interface Annotation {
  id: string
  text: string
  type: 'entity' | 'keyword' | 'sensitive' | 'custom'
  label: string
  start: number
  end: number
}

interface DataAnnotatorProps {
  content: string
  annotations?: Annotation[]
  onAnnotate: (annotations: Annotation[]) => void
  onDocumentTags?: (tags: string[]) => void
}

type AnnotationTypeId = Annotation['type']
type AnnotationTone = 'info' | 'success' | 'destructive' | 'primary'
type AutoTagProviderId = 'cpu' | 'llm' | 'compliance' | 'hybrid'
const ANNOTATION_TYPE_CONFIGS: Array<{
  id: AnnotationTypeId
  icon: typeof Hash
  tone: AnnotationTone
}> = [
  { id: 'entity', icon: Hash, tone: 'info' },
  { id: 'keyword', icon: Highlighter, tone: 'success' },
  { id: 'sensitive', icon: Shield, tone: 'destructive' },
  { id: 'custom', icon: Type, tone: 'primary' },
]

const AUTO_TAG_PROVIDER_OPTIONS: Array<{
  id: AutoTagProviderId
  providers: NonNullable<AutoAnnotationRequest['providers']>
  enableLlm: boolean
  enableSensitive: boolean
}> = [
  { id: 'cpu', providers: ['cpu'], enableLlm: false, enableSensitive: false },
  { id: 'llm', providers: ['llm'], enableLlm: true, enableSensitive: false },
  { id: 'compliance', providers: ['pii', 'secret', 'regex'], enableLlm: false, enableSensitive: true },
  { id: 'hybrid', providers: ['cpu', 'llm', 'gliner', 'pii', 'secret'], enableLlm: true, enableSensitive: true },
]
const DEFAULT_AUTO_TAG_PROVIDER: AutoTagProviderId = 'cpu'

const DOCUMENT_TAG_LABELS: Record<AutoDocumentTag['type'], string> = {
  topic: '主题',
  category: '分类',
  domain: '领域',
  industry: '行业',
  doc_type: '文档类型',
  sensitivity: '敏感级别',
  quality: '质量',
  keyword: '关键词',
}

function documentTagLabel(tag: AutoDocumentTag): string {
  if (tag.type !== 'sensitivity') return tag.value
  const labels: Record<string, string> = { public: '公开', internal: '内部', confidential: '机密', restricted: '受限' }
  return labels[tag.value.toLowerCase()] ?? tag.value
}

function isLongTag(tag: AutoDocumentTag): boolean {
  return tag.value.length > 32 || /[\r\n]/.test(tag.value)
}

function getSelectionRoot(): HTMLElement | null {
  if (globalThis.document === undefined) return null
  return globalThis.document.querySelector('[data-governance-selection-root="true"]')
}

function normalizeSelectedText(value: string): string {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function findSelectionRange(content: string, selectedText: string): { start: number; end: number; text: string } | null {
  const text = String(selectedText || '').trim()
  if (!content || !text) return null

  const exactStart = content.indexOf(text)
  if (exactStart >= 0) return { start: exactStart, end: exactStart + text.length, text }


  return null
}

function dedupeAnnotations(items: Annotation[]): Annotation[] {
  const seen = new Set<string>()
  const out: Annotation[] = []
  for (const item of items) {
    const key = `${item.type}:${item.start}:${item.end}:${item.text}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push(item)
  }
  return out
}

export function DataAnnotator({ content, annotations = [], onAnnotate, onDocumentTags }: Readonly<DataAnnotatorProps>) {
  const t = useTranslations('DataAnnotator')
  const annotationTypes = useMemo(
    () =>
      ANNOTATION_TYPE_CONFIGS.map(({ id, icon, tone }) => ({
        id,
        icon,
        tone,
        label: t(`types.${id}.label`),
        description: t(`types.${id}.description`),
      })),
    [t]
  )
  const [selectedType, setSelectedType] = useState<AnnotationTypeId>('keyword')
  const [customLabel, setCustomLabel] = useState('')
  const [isSelecting, setIsSelecting] = useState(false)
  const [isAutoTagging, setIsAutoTagging] = useState(false)
  const [autoTagProvider, setAutoTagProvider] = useState<AutoTagProviderId>(DEFAULT_AUTO_TAG_PROVIDER)
  const [selection, setSelection] = useState<{ start: number; end: number; text: string } | null>(null)
  const [localAnnotations, setLocalAnnotations] = useState<Annotation[]>(annotations)
  const [semanticSummary, setSemanticSummary] = useState<string | null>(null)
  const [semanticTags, setSemanticTags] = useState<AutoDocumentTag[]>([])
  const contentRef = useRef(content)
  useEffect(() => { contentRef.current = content }, [content])

  const annotationsByType = useMemo(() => {
    const grouped: Record<AnnotationTypeId, Annotation[]> = {
      entity: [],
      keyword: [],
      sensitive: [],
      custom: [],
    }

    localAnnotations.forEach((annotation) => {
      grouped[annotation.type].push(annotation)
    })

    return grouped
  }, [localAnnotations])

  const documentTagGroups = useMemo(() => {
    const compact = semanticTags.filter(tag => !isLongTag(tag))
    return {
      attributes: Object.entries(DOCUMENT_TAG_LABELS)
        .filter(([type]) => type !== 'keyword' && type !== 'topic')
        .map(([type, label]) => ({ type, label, tags: compact.filter(tag => tag.type === type) }))
        .filter(group => group.tags.length > 0),
      terms: (['topic', 'keyword'] as const)
        .map(type => ({ type, label: DOCUMENT_TAG_LABELS[type], tags: compact.filter(tag => tag.type === type) }))
        .filter(group => group.tags.length > 0),
      excerpts: semanticTags.filter(isLongTag),
    }
  }, [semanticTags])

  const typeConfig = annotationTypes.find((type) => type.id === selectedType) ?? annotationTypes[0]
  const selectedProviderConfig =
    AUTO_TAG_PROVIDER_OPTIONS.find((option) => option.id === autoTagProvider) ?? AUTO_TAG_PROVIDER_OPTIONS[0]

  useEffect(() => {
    setLocalAnnotations(annotations)
  }, [annotations])

  useEffect(() => {
    setSemanticSummary(null)
    setSemanticTags([])
  }, [content])

  useEffect(() => {
    if (!content && selection) {
      setSelection(null)
      setIsSelecting(false)
    }
  }, [content, selection])

  const commitAnnotations = useCallback(
    (updater: (prev: Annotation[]) => Annotation[]) => {
      const next = dedupeAnnotations(updater(localAnnotations))
      setLocalAnnotations(next)
      onAnnotate(next)
    },
    [localAnnotations, onAnnotate]
  )

  useEffect(() => {
    if (!isSelecting) return

    const captureSelection = () => {
      const activeSelection = globalThis.getSelection?.()
      const selectedText = activeSelection?.toString() || ''
      if (!normalizeSelectedText(selectedText)) return

      const root = getSelectionRoot()
      const anchorNode = activeSelection?.anchorNode || null
      const focusNode = activeSelection?.focusNode || null
      if (root && anchorNode && !root.contains(anchorNode)) return
      if (root && focusNode && !root.contains(focusNode)) return

      const nextSelection = findSelectionRange(content, selectedText)
      if (nextSelection) setSelection(nextSelection)
    }

    globalThis.document?.addEventListener('mouseup', captureSelection)
    globalThis.document?.addEventListener('keyup', captureSelection)
    return () => {
      globalThis.document?.removeEventListener('mouseup', captureSelection)
      globalThis.document?.removeEventListener('keyup', captureSelection)
    }
  }, [content, isSelecting])

  const handleAddAnnotation = () => {
    if (!selection || !typeConfig) return

    const label = selectedType === 'custom' ? customLabel.trim() : typeConfig.label
    if (!label) return

    const nextAnnotation: Annotation = {
      id: globalThis.crypto?.randomUUID?.() ?? `${selection.start}-${selection.end}-${localAnnotations.length}`,
      text: selection.text,
      type: selectedType,
      label,
      start: selection.start,
      end: selection.end,
    }

    commitAnnotations((prev) => [...prev, nextAnnotation])
    setSelection(null)
    setIsSelecting(false)
    if (selectedType === 'custom') {
      setCustomLabel('')
    }
  }

  const handleDeleteAnnotation = (annotationId: string) => {
    commitAnnotations((prev) => prev.filter((annotation) => annotation.id !== annotationId))
  }

  const handleAutoAnnotate = async () => {
    const source = String(content || '')
    if (!source.trim() || isAutoTagging) {
      toast.warning(t('auto.empty'))
      return
    }

    setIsAutoTagging(true)
    try {
      const response = await pipelineApi.autoAnnotations({
        text: source,
        mode: 'document_focus',
        providers: selectedProviderConfig.providers,
        enable_llm: selectedProviderConfig.enableLlm,
        enable_llm_topics: selectedProviderConfig.enableLlm,
        enable_keywords: true,
        enable_entities: true,
        enable_sensitive: selectedProviderConfig.enableSensitive,
        keyword_provider: 'simple',
        keyword_top_k: 12,
        max_annotations: 80,
      })
      if (contentRef.current !== source) return
      const nextSemanticTags = response.document_tags || []
      setSemanticSummary(response.summary ?? null)
      setSemanticTags(nextSemanticTags)
      if (nextSemanticTags.length > 0) {
        onDocumentTags?.(nextSemanticTags.map((tag) => tag.value))
      }
      const candidates: Annotation[] = (response.annotations || []).map((item, index) => ({
        id:
          globalThis.crypto?.randomUUID?.() ??
          `auto-${item.type}-${item.start}-${item.end}-${index}`,
        text: item.text,
        type: item.type,
        label: item.label || annotationTypes.find((type) => type.id === item.type)?.label || item.type,
        start: item.start,
        end: item.end,
      }))

      const before = localAnnotations.length
      commitAnnotations((prev) => [...prev, ...candidates])
      const added = dedupeAnnotations([...localAnnotations, ...candidates]).length - before
      if (added > 0) {
        toast.success(t('auto.success', { count: added }))
      } else if (nextSemanticTags.length > 0) {
        toast.info(t('auto.semanticOnly', { count: nextSemanticTags.length }))
      } else {
        toast.info(t('auto.noCandidates'))
      }
    } catch (err) {
      reportClientWarning('Auto annotation failed', err)
      toast.error(t('auto.failed'))
    } finally {
      setIsAutoTagging(false)
    }
  }

  return (
    <>
      <div className={styles.toolLine}>
        <div className={styles.toolIdentity}><strong>文本标注</strong><span>{localAnnotations.length} 条标注</span></div>
        <div className={styles.toolActions}>
          <select className={styles.fieldControl} aria-label="自动标注方式" value={autoTagProvider} onChange={event => setAutoTagProvider(event.target.value as AutoTagProviderId)} disabled={isAutoTagging}>
            {AUTO_TAG_PROVIDER_OPTIONS.map(option => <option key={option.id} value={option.id}>{t('auto.providers.' + option.id + '.label')}</option>)}
          </select>
          <Button disabled={isAutoTagging || !content.trim()} onClick={() => void handleAutoAnnotate()}>{isAutoTagging ? <Loader2 className={styles.spinner} /> : <Tag className="size-4" />}{isAutoTagging ? '正在标注…' : '自动标注'}</Button>
        </div>
      </div>
      <div className={styles.toolBody}>
        <div className={styles.formRow}>
          <div className={styles.fieldGroup}>
            <label htmlFor="governance-annotation-type">标注类型</label>
            <select className={styles.fieldControl} id="governance-annotation-type" value={selectedType} onChange={event => setSelectedType(event.target.value as AnnotationTypeId)}>
              {annotationTypes.map(type => <option key={type.id} value={type.id}>{type.label} · {annotationsByType[type.id].length}</option>)}
            </select>
          </div>
          {selectedType === 'custom' && <input className={styles.fieldControl} aria-label="自定义标注名称" placeholder="标签名称" value={customLabel} onChange={event => setCustomLabel(event.target.value)} />}
          <Button variant="outline" disabled={!content.trim()} aria-pressed={isSelecting} onClick={() => { setIsSelecting(value => !value); setSelection(null) }}><Highlighter className="size-4" />{isSelecting ? '取消选取' : '选择正文文字'}</Button>
          {isSelecting && !selection && <span className={styles.fieldHint}>在下方正文中选中需要标注的文字</span>}
        </div>
        {selection && <div className={styles.selection}><p>{selection.text}</p><Button size="sm" variant="outline" disabled={selectedType === 'custom' && !customLabel.trim()} onClick={handleAddAnnotation}>添加{typeConfig.label}标注</Button></div>}
        {semanticTags.length > 0 || semanticSummary ? <section className={styles.annotationResults} aria-label="文档标签">
          {semanticSummary && <p className={styles.annotationSummary}>{semanticSummary}</p>}
          {documentTagGroups.attributes.length > 0 && <dl className={styles.annotationAttributes}>
            {documentTagGroups.attributes.map(group => <div key={group.type}>
              <dt>{group.label}</dt>
              <dd>{group.tags.map((tag, index) => <span key={tag.value + ':' + index}>{documentTagLabel(tag)}</span>)}</dd>
            </div>)}
          </dl>}
          {documentTagGroups.terms.map(group => <div className={styles.annotationKeywords} key={group.type}>
            <h3>{group.label}</h3>
            <ul aria-label={group.label}>{group.tags.map((tag, index) => <li key={tag.value + ':' + index}>{tag.value}</li>)}</ul>
          </div>)}
        </section> : null}
        {documentTagGroups.excerpts.length > 0 || localAnnotations.length > 0 ? <div className={styles.annotationDetails}>
          {documentTagGroups.excerpts.length > 0 && <details className={styles.annotationDisclosure}>
            <summary><ChevronRight aria-hidden="true" /><span>长文本标签</span><span className={styles.annotationCount}>{documentTagGroups.excerpts.length}</span></summary>
            <ul className={styles.annotationExcerpts}>
              {documentTagGroups.excerpts.map((tag, index) => <li key={tag.type + ':' + index}><span>{DOCUMENT_TAG_LABELS[tag.type]}</span><p>{tag.value}</p></li>)}
            </ul>
          </details>}
          {localAnnotations.length > 0 && <details className={styles.annotationDisclosure}>
            <summary><ChevronRight aria-hidden="true" /><span>正文标注</span><span className={styles.annotationCount}>{localAnnotations.length}</span></summary>
            <ul aria-label="正文标注" className={styles.annotationList}>
              {localAnnotations.map(annotation => <li className={styles.annotationRow} key={annotation.id}>
                <span className={styles.annotationKind} data-tone={annotationTypes.find(type => type.id === annotation.type)?.tone}>{annotation.label}</span>
                <p>{annotation.text}</p>
                <Button size="icon" variant="ghost" className={styles.annotationDelete} aria-label={'删除标注 ' + annotation.text} onClick={() => handleDeleteAnnotation(annotation.id)}><X className="size-4" /></Button>
              </li>)}
            </ul>
          </details>}
        </div> : null}
      </div>
    </>
  )
}
