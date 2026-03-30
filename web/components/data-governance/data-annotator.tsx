'use client'

import { useEffect, useMemo, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Hash,
  Highlighter,
  Plus,
  Search,
  Shield,
  Tag,
  Type,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

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
}

type AnnotationTypeId = Annotation['type']
type AnnotationTone = 'info' | 'success' | 'destructive' | 'primary'
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

export function DataAnnotator({ content, annotations = [], onAnnotate }: Readonly<DataAnnotatorProps>) {
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
  const [selection, setSelection] = useState<{ start: number; end: number; text: string } | null>(null)
  const [localAnnotations, setLocalAnnotations] = useState<Annotation[]>(annotations)
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

  useEffect(() => {
    setLocalAnnotations(annotations)
  }, [annotations])

  useEffect(() => {
    if (!content && selection) {
      setSelection(null)
      setIsSelecting(false)
    }
  }, [content, selection])

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

    setLocalAnnotations((prev) => {
      const next = [...prev, nextAnnotation]
      onAnnotate(next)
      return next
    })
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
    setLocalAnnotations((prev) => {
      const next = prev.filter((annotation) => annotation.id !== annotationId)
      onAnnotate(next)
      return next
    })
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center gap-2">
        <Tag className="h-5 w-5 text-primary" />
        <h3 className="font-bold text-foreground">{t('header.title')}</h3>
      </div>

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
            <Search className="h-4 w-4 text-primary" />
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
          <Highlighter className="h-4 w-4" />
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
                  <Icon className={cn('h-4 w-4', getToneStyles(type.tone).icon)} />
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
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
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
            <Tag className="mx-auto mb-2 h-10 w-10 opacity-30" />
            <p className="text-sm">{t('empty.title')}</p>
            <p className="mt-1 text-xs">{t('empty.description')}</p>
          </div>
        )}
      </div>
    </div>
  )
}
