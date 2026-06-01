'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Hash,
  Highlighter,
  Loader2,
  Plus,
  Search,
  Shield,
  Sparkles,
  Tag,
  Type,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { pipelineApi } from '@/lib/api'
import { reportClientWarning } from '@/lib/client-logging'
import { cn } from '@/lib/utils'
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
type AnnotationTypeConfig = {
  id: AnnotationTypeId
  label: string
  icon: LucideIcon
  tone: AnnotationTone
  description: string
}

const ANNOTATION_TYPE_CONFIGS: Array<{
  id: AnnotationTypeId
  icon: LucideIcon
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

const TONE_STYLES: Record<
  AnnotationTone,
  { selected: string; iconWrap: string; icon: string; text: string; pill: string; mark: string }
> = {
  info: {
    selected: 'bg-info/10 border-info/30 ring-1 ring-info/20',
    iconWrap: 'bg-info/10',
    icon: 'text-info',
    text: 'text-info',
    pill: 'bg-info/10 text-info border-info/20',
    mark: 'bg-info/15 text-info border border-info/20',
  },
  success: {
    selected: 'bg-success/10 border-success/30 ring-1 ring-success/20',
    iconWrap: 'bg-success/10',
    icon: 'text-success',
    text: 'text-success',
    pill: 'bg-success/10 text-success border-success/20',
    mark: 'bg-success/15 text-success border border-success/20',
  },
  destructive: {
    selected: 'bg-destructive/10 border-destructive/30 ring-1 ring-destructive/20',
    iconWrap: 'bg-destructive/10',
    icon: 'text-destructive',
    text: 'text-destructive',
    pill: 'bg-destructive/10 text-destructive border-destructive/20',
    mark: 'bg-destructive/15 text-destructive border border-destructive/20',
  },
  primary: {
    selected: 'bg-primary/10 border-primary/30 ring-1 ring-primary/20',
    iconWrap: 'bg-primary/10',
    icon: 'text-primary',
    text: 'text-primary',
    pill: 'bg-primary/10 text-primary border-primary/20',
    mark: 'bg-primary/15 text-primary border border-primary/20',
  },
}

function getToneStyles(tone: AnnotationTone) {
  return TONE_STYLES[tone]
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

  const normalizedSelection = normalizeSelectedText(text)
  const normalizedContent = normalizeSelectedText(content)
  const normalizedStart = normalizedContent.indexOf(normalizedSelection)
  if (normalizedStart >= 0) {
    return {
      start: normalizedStart,
      end: normalizedStart + normalizedSelection.length,
      text: normalizedSelection,
    }
  }

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
  const [autoTagProvider, setAutoTagProvider] = useState<AutoTagProviderId>('cpu')
  const [selection, setSelection] = useState<{ start: number; end: number; text: string } | null>(null)
  const [localAnnotations, setLocalAnnotations] = useState<Annotation[]>(annotations)
  const [semanticSummary, setSemanticSummary] = useState<string | null>(null)
  const [semanticTags, setSemanticTags] = useState<AutoDocumentTag[]>([])
  const [expandedTypes, setExpandedTypes] = useState<Set<AnnotationTypeId>>(new Set())

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
      setLocalAnnotations((prev) => {
        const next = dedupeAnnotations(updater(prev))
        onAnnotate(next)
        return next
      })
    },
    [onAnnotate]
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

  const toggleExpandedType = (typeId: AnnotationTypeId) => {
    setExpandedTypes((prev) => {
      const next = new Set(prev)
      if (next.has(typeId)) next.delete(typeId)
      else next.add(typeId)
      return next
    })
  }

  const handleDeleteAnnotation = (annotationId: string) => {
    commitAnnotations((prev) => prev.filter((annotation) => annotation.id !== annotationId))
  }

  const handleAutoAnnotate = async () => {
    const source = String(content || '').trim()
    if (!source) {
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
    <div className="space-y-6 p-6">
      <div className="flex items-center gap-2">
        <Tag className="size-5 text-primary" />
        <h3 className="font-medium text-foreground">{t('header.title')}</h3>
      </div>

      <div className="space-y-2">
        <div className="text-xs font-medium text-muted-foreground">{t('auto.providerTitle')}</div>
        <div className="grid grid-cols-2 gap-2">
          {AUTO_TAG_PROVIDER_OPTIONS.map((option) => {
            const selected = autoTagProvider === option.id
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => setAutoTagProvider(option.id)}
                className={cn(
                  'focus-ring rounded-xl border px-3 py-2 text-left transition-colors',
                  selected
                    ? 'border-primary/30 bg-primary/10 text-primary shadow-[inset_0_1px_0_rgba(255,255,255,0.8)]'
                    : 'border-border bg-card text-muted-foreground hover:bg-muted'
                )}
              >
                <div className="text-xs font-medium text-foreground">{t(`auto.providers.${option.id}.label`)}</div>
                <div className="mt-1 text-[11px] leading-4 text-muted-foreground">{t(`auto.providers.${option.id}.description`)}</div>
              </button>
            )
          })}
        </div>
      </div>

      <Button
        type="button"
        onClick={() => void handleAutoAnnotate()}
        disabled={isAutoTagging || !content.trim()}
        variant="outline"
        size="sm"
        className="w-full gap-2 border-primary/20 bg-primary/5 text-primary hover:bg-primary/10"
      >
        {isAutoTagging ? (
          <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
        ) : (
          <Sparkles className="size-4" />
        )}
        {isAutoTagging ? t('auto.running') : t('auto.action')}
      </Button>

      {(semanticSummary || semanticTags.length > 0) && (
        <div className="rounded-2xl border border-primary/15 bg-card p-4 shadow-sm shadow-primary/10">
          <div className="mb-2 flex items-center gap-2">
            <Sparkles className="size-4 text-primary" />
            <div className="text-sm font-semibold text-foreground">{t('semantic.title')}</div>
          </div>
          {semanticSummary && (
            <p className="mb-3 line-clamp-3 text-xs leading-5 text-muted-foreground">{semanticSummary}</p>
          )}
          {semanticTags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {semanticTags.slice(0, 16).map((tag) => (
                <span
                  key={`${tag.type}-${tag.value}`}
                  title={`${tag.source} · ${(tag.confidence * 100).toFixed(0)}%`}
                  className="inline-flex max-w-full items-center gap-1 rounded-full border border-primary/15 bg-background/80 px-2 py-1 text-xs text-foreground/80"
                >
                  <span className="text-muted-foreground">{tag.label || tag.type}</span>
                  <span className="truncate font-medium">{tag.value}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="space-y-2">
        <div className="text-xs font-medium text-muted-foreground">{t('sections.typeSelector')}</div>
        <div className="grid grid-cols-2 gap-2">
          {annotationTypes.map((type) => {
            const Icon = type.icon
            const isSelected = selectedType === type.id
            const count = annotationsByType[type.id].length

            return (
              <button
                key={type.id}
                type="button"
                title={type.description}
                onClick={() => setSelectedType(type.id)}
                className={cn(
                  'focus-ring flex items-center gap-2 rounded-lg border p-2.5 text-left transition-colors duration-200 motion-reduce:transition-none',
                  isSelected ? getToneStyles(type.tone).selected : 'border-border bg-muted hover:bg-muted'
                )}
              >
                <div
                  className={cn(
                    'flex h-7 w-7 items-center justify-center rounded-lg',
                    getToneStyles(type.tone).iconWrap
                  )}
                >
                  <Icon className={cn('h-3.5 w-3.5', getToneStyles(type.tone).icon)} />
                </div>
                <div className="min-w-0 flex-1">
                  <div
                    className={cn(
                      'text-sm font-medium',
                      isSelected ? getToneStyles(type.tone).text : 'text-foreground/80'
                    )}
                  >
                    {type.label}
                  </div>
                  <div className="text-xs text-muted-foreground">{t('counts.typeCount', { count })}</div>
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {selectedType === 'custom' && (
        <div>
          <Input
            type="text"
            placeholder={t('custom.placeholder')}
            value={customLabel}
            onChange={(event) => setCustomLabel(event.target.value)}
            className="w-full"
          />
        </div>
      )}

      {selection ? (
        <div className="rounded-xl border border-primary/20 bg-primary/10 p-4">
          <div className="mb-2 flex items-center gap-2">
            <Search className="size-4 text-primary" />
            <span className="text-sm font-medium text-primary">{t('selection.title')}</span>
          </div>
          <div className="mb-3 rounded border border-primary/20 bg-card p-2">
            <div className="line-clamp-2 text-sm text-foreground/80">{selection.text}</div>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={handleAddAnnotation} size="sm" className="flex-1 gap-1.5">
              <Plus className="h-3.5 w-3.5" />
              {t('selection.add', { label: typeConfig?.label ?? '' })}
            </Button>
            <Button onClick={() => setSelection(null)} variant="outline" size="sm">
              {t('selection.cancel')}
            </Button>
          </div>
        </div>
      ) : (
        <Button
          onClick={() => setIsSelecting((prev) => !prev)}
          variant={isSelecting ? 'default' : 'outline'}
          size="sm"
          className="w-full gap-2"
        >
          <Highlighter className="size-4" />
          {isSelecting ? t('selection.activePrompt') : t('selection.start')}
        </Button>
      )}

      <div className="space-y-2">
        <div className="text-xs font-medium text-muted-foreground">
          {t('sections.existing', { count: localAnnotations.length })}
        </div>

        {annotationTypes.map((type) => {
          const items = annotationsByType[type.id]
          const Icon = type.icon
          const isExpanded = expandedTypes.has(type.id)

          if (items.length === 0) return null

          return (
            <div key={type.id} className="overflow-hidden rounded-xl border border-border">
              <button
                type="button"
                onClick={() => toggleExpandedType(type.id)}
                className="flex w-full items-center justify-between p-3 transition-colors hover:bg-muted motion-reduce:transition-none"
              >
                <div className="flex items-center gap-2">
                  <Icon className={cn('size-4', getToneStyles(type.tone).icon)} />
                  <span className="text-sm font-medium text-foreground/80">{type.label}</span>
                  <span
                    className={cn(
                      'rounded-full border px-1.5 py-0.5 text-xs',
                      getToneStyles(type.tone).pill
                    )}
                  >
                    {items.length}
                  </span>
                </div>
                {isExpanded ? (
                  <ChevronDown className="size-4 text-muted-foreground" />
                ) : (
                  <ChevronRight className="size-4 text-muted-foreground" />
                )}
              </button>

              {isExpanded && (
                <div className="space-y-2 border-t border-border p-3 pt-0">
                  {items.map((anno) => (
                    <div
                      key={anno.id}
                      className="flex items-center justify-between rounded-lg bg-muted p-2"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="text-xs text-muted-foreground">
                          {t('annotation.position', { start: anno.start, end: anno.end })}
                        </div>
                        <div className="truncate text-sm text-foreground/80">{anno.text}</div>
                      </div>
                      <Button
                        onClick={() => handleDeleteAnnotation(anno.id)}
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                        aria-label={t('a11y.deleteAnnotation', {
                          label: type.label,
                          start: anno.start,
                          end: anno.end,
                        })}
                      >
                        <X className="h-3.5 w-3.5" aria-hidden="true" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}

        {localAnnotations.length === 0 && (
          <div className="py-8 text-center text-muted-foreground">
            <Tag className="mx-auto mb-2 size-10 opacity-30" />
            <p className="text-sm">{t('empty.title')}</p>
            <p className="mt-1 text-xs">{t('empty.description')}</p>
          </div>
        )}
      </div>
    </div>
  )
}
