'use client'

import { useCallback, useMemo, useState } from 'react'
import { Check, FileText, Folder, FolderTree, Plus, Sparkles, Tag, X } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

interface DataClassifierProps {
  content: string
  initialCategory?: string | null
  initialTags?: string[]
  onClassify: (category: string, tags: string[]) => void
}

type CategoryId = 'technical' | 'product' | 'business' | 'legal' | 'hr' | 'finance' | 'other'
type SuggestedTagId =
  | 'important'
  | 'public'
  | 'internal'
  | 'confidential'
  | 'reviewPending'
  | 'archived'
  | 'version1'
  | 'version2'
  | 'latest'
  | 'historical'
  | 'faq'
  | 'tutorial'
  | 'guide'
  | 'reference'
  | 'api'
  | 'urgent'
  | 'longTerm'
  | 'temporary'

const PRESET_CATEGORY_CONFIGS: Array<{
  id: CategoryId
  icon: typeof FileText
  tone: 'info' | 'success' | 'primary' | 'destructive' | 'warning' | 'neutral'
}> = [
  { id: 'technical', icon: FileText, tone: 'info' },
  { id: 'product', icon: FileText, tone: 'success' },
  { id: 'business', icon: Folder, tone: 'primary' },
  { id: 'legal', icon: Folder, tone: 'destructive' },
  { id: 'hr', icon: Folder, tone: 'warning' },
  { id: 'finance', icon: Folder, tone: 'warning' },
  { id: 'other', icon: Folder, tone: 'neutral' },
]

const SUGGESTED_TAG_IDS: SuggestedTagId[] = [
  'important',
  'public',
  'internal',
  'confidential',
  'reviewPending',
  'archived',
  'version1',
  'version2',
  'latest',
  'historical',
  'faq',
  'tutorial',
  'guide',
  'reference',
  'api',
  'urgent',
  'longTerm',
  'temporary',
]

type CategoryTone = (typeof PRESET_CATEGORY_CONFIGS)[number]['tone']

const CATEGORY_TONE_STYLES: Record<
  CategoryTone,
  { selected: string; iconWrap: string; icon: string; text: string }
> = {
  info: {
    selected: 'bg-info/10 border-info/30 ring-1 ring-info/20',
    iconWrap: 'bg-info/10',
    icon: 'text-info',
    text: 'text-info',
  },
  success: {
    selected: 'bg-success/10 border-success/30 ring-1 ring-success/20',
    iconWrap: 'bg-success/10',
    icon: 'text-success',
    text: 'text-success',
  },
  warning: {
    selected: 'bg-warning/10 border-warning/30 ring-1 ring-warning/20',
    iconWrap: 'bg-warning/10',
    icon: 'text-warning',
    text: 'text-warning',
  },
  destructive: {
    selected: 'bg-destructive/10 border-destructive/30 ring-1 ring-destructive/20',
    iconWrap: 'bg-destructive/10',
    icon: 'text-destructive',
    text: 'text-destructive',
  },
  primary: {
    selected: 'bg-primary/10 border-primary/30 ring-1 ring-primary/20',
    iconWrap: 'bg-primary/10',
    icon: 'text-primary',
    text: 'text-primary',
  },
  neutral: {
    selected: 'bg-muted border-border ring-1 ring-border/60',
    iconWrap: 'bg-muted',
    icon: 'text-muted-foreground',
    text: 'text-foreground',
  },
}

function getCategoryToneStyles(tone: CategoryTone) {
  return CATEGORY_TONE_STYLES[tone]
}

function getSuggestionChipClassName(isAdded: boolean, isRecommended: boolean) {
  if (isAdded) {
    return 'cursor-default border-primary/20 bg-primary/15 text-primary'
  }

  if (isRecommended) {
    return 'border-info/20 bg-info/10 text-info hover:bg-info/15'
  }

  return 'border-border bg-muted text-muted-foreground hover:bg-accent/40 hover:text-foreground'
}

export function DataClassifier({
  content,
  initialCategory = null,
  initialTags = [],
  onClassify,
}: Readonly<DataClassifierProps>) {
  const t = useTranslations('DataClassifier')
  const categories = useMemo(
    () =>
      PRESET_CATEGORY_CONFIGS.map(({ id, icon, tone }) => ({
        id,
        icon,
        tone,
        label: t(`categories.${id}.label`),
        keywords: t.raw(`categories.${id}.keywords`) as string[],
      })),
    [t]
  )
  const suggestedTagLabels = t.raw('suggestedTags') as string[]
  const suggestedTagMap = useMemo(
    () =>
      Object.fromEntries(
        SUGGESTED_TAG_IDS.map((id, index) => [id, suggestedTagLabels[index] ?? id])
      ) as Record<SuggestedTagId, string>,
    [suggestedTagLabels]
  )
  const [selectedCategory, setSelectedCategory] = useState<string | null>(initialCategory)
  const [tags, setTags] = useState<string[]>(initialTags)
  const [newTag, setNewTag] = useState('')
  const [isAutoClassifying, setIsAutoClassifying] = useState(false)
  const [suggestedTags, setSuggestedTags] = useState<string[]>([])
  const [showAllTags, setShowAllTags] = useState(false)

  const handleAutoClassify = useCallback(async () => {
    setIsAutoClassifying(true)

    await new Promise((resolve) => setTimeout(resolve, 1000))

    const contentLower = content.toLowerCase()
    let bestMatch: CategoryId = 'other'
    let maxScore = 0

    categories.forEach((category) => {
      const score = category.keywords.reduce((sum, keyword) => {
        return sum + (contentLower.includes(keyword.toLowerCase()) ? 1 : 0)
      }, 0)

      if (score > maxScore) {
        maxScore = score
        bestMatch = category.id
      }
    })

    const category = categories.find((item) => item.id === bestMatch) ?? categories[categories.length - 1]
    setSelectedCategory(category.label)

    const recommendations: string[] = []
    if (contentLower.includes('重要') || contentLower.includes('必须')) {
      recommendations.push(suggestedTagMap.important)
    }
    if (contentLower.includes('faq') || contentLower.includes('常见')) {
      recommendations.push(suggestedTagMap.faq)
    }
    if (contentLower.includes('教程') || contentLower.includes('指南')) {
      recommendations.push(suggestedTagMap.tutorial)
    }
    if (contentLower.includes('api')) {
      recommendations.push(suggestedTagMap.api)
    }
    if (contentLower.includes('版本') || contentLower.includes('v1')) {
      recommendations.push(suggestedTagMap.version1)
    }

    setSuggestedTags(recommendations)
    setIsAutoClassifying(false)
    onClassify(category.label, tags)
  }, [categories, content, onClassify, suggestedTagMap, tags])

  const handleAddTag = useCallback(
    (tag: string) => {
      if (tag && !tags.includes(tag)) {
        const updated = [...tags, tag]
        setTags(updated)
        onClassify(selectedCategory || '', updated)
      }

      setNewTag('')
    },
    [onClassify, selectedCategory, tags]
  )

  const handleRemoveTag = useCallback(
    (tag: string) => {
      const updated = tags.filter((item) => item !== tag)
      setTags(updated)
      onClassify(selectedCategory || '', updated)
    },
    [onClassify, selectedCategory, tags]
  )

  const handleSelectCategory = useCallback(
    (categoryId: CategoryId) => {
      const category = categories.find((item) => item.id === categoryId)
      if (!category) return
      setSelectedCategory(category.label)
      onClassify(category.label, tags)
    },
    [categories, onClassify, tags]
  )

  const displayTags = showAllTags ? suggestedTagLabels : suggestedTagLabels.slice(0, 8)

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FolderTree className="size-5 text-primary" />
          <h3 className="font-bold text-foreground">{t('header.title')}</h3>
        </div>
        <Button
          onClick={handleAutoClassify}
          disabled={isAutoClassifying}
          size="sm"
          variant="outline"
          className="gap-1.5"
        >
          {isAutoClassifying ? (
            <>
              <div className="h-3.5 w-3.5 rounded-full border-2 border-muted-foreground/30 border-t-primary motion-safe:animate-spin motion-reduce:animate-none" />
              {t('actions.analyzing')}
            </>
          ) : (
            <>
              <Sparkles className="h-3.5 w-3.5" />
              {t('actions.autoClassify')}
            </>
          )}
        </Button>
      </div>

      <div className="space-y-2">
        <div className="text-xs font-medium text-muted-foreground">{t('sections.category')}</div>
        <div className="grid grid-cols-2 gap-2">
          {categories.map((category) => {
            const Icon = category.icon
            const isSelected = selectedCategory === category.label
            const tone = getCategoryToneStyles(category.tone)

            return (
              <button
                key={category.id}
                type="button"
                onClick={() => handleSelectCategory(category.id)}
                className={cn(
                  'focus-ring flex items-center gap-2 rounded-xl border p-3 text-left transition-colors duration-200 motion-reduce:transition-none',
                  isSelected ? tone.selected : 'border-border bg-muted hover:bg-muted'
                )}
              >
                <div className={cn('flex h-8 w-8 items-center justify-center rounded-lg', tone.iconWrap)}>
                  <Icon className={cn('size-4', tone.icon)} />
                </div>
                <span className={cn('text-sm font-medium', isSelected ? tone.text : 'text-foreground/80')}>
                  {category.label}
                </span>
                {isSelected && <Check className={cn('ml-auto size-4', tone.icon)} />}
              </button>
            )
          })}
        </div>
      </div>

      <div className="space-y-3">
        <div className="text-xs font-medium text-muted-foreground">{t('sections.tags')}</div>

        {tags.length > 0 && (
          <div className="flex flex-wrap gap-2 rounded-xl bg-muted p-3">
            {tags.map((tag) => (
              <span
                key={tag}
                className="inline-flex items-center gap-1 rounded-lg border border-border/60 bg-secondary/60 px-2.5 py-1 text-sm text-foreground"
              >
                <Tag className="size-3" />
                {tag}
                <button
                  type="button"
                  onClick={() => handleRemoveTag(tag)}
                  aria-label={t('a11y.removeTagWithValue', { tag })}
                  className="ml-1 text-muted-foreground hover:text-destructive"
                >
                  <X className="size-3" aria-hidden="true" />
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <Input
            type="text"
            placeholder={t('tags.inputPlaceholder')}
            value={newTag}
            onChange={(event) => setNewTag(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                handleAddTag(newTag)
              }
            }}
            className="flex-1"
          />
          <Button
            onClick={() => handleAddTag(newTag)}
            disabled={!newTag || tags.includes(newTag)}
            size="sm"
            aria-label={newTag ? t('a11y.addTagWithValue', { tag: newTag }) : t('a11y.addTag')}
          >
            <Plus className="size-4" aria-hidden="true" />
          </Button>
        </div>

        {(suggestedTags.length > 0 || suggestedTagLabels.length > 0) && (
          <div className="space-y-2">
            {suggestedTags.length > 0 && (
              <div className="flex items-center gap-2 text-xs text-info">
                <Sparkles className="h-3.5 w-3.5" />
                <span>{t('tags.aiSuggested')}</span>
              </div>
            )}

            <div className="flex flex-wrap gap-1.5">
              {(suggestedTags.length > 0 ? suggestedTags : displayTags).map((tag) => {
                const isAdded = tags.includes(tag)
                const isRecommended = suggestedTags.includes(tag)

                return (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => !isAdded && handleAddTag(tag)}
                    disabled={isAdded}
                    className={cn(
                      'inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs transition-colors duration-200 motion-reduce:transition-none',
                      getSuggestionChipClassName(isAdded, isRecommended)
                    )}
                  >
                    {isRecommended && !isAdded && <Sparkles className="size-3" />}
                    {tag}
                  </button>
                )
              })}
            </div>

            {suggestedTagLabels.length > 8 && !showAllTags && suggestedTags.length === 0 && (
              <button
                type="button"
                onClick={() => setShowAllTags(true)}
                className="text-xs text-muted-foreground hover:text-muted-foreground"
              >
                {t('tags.showMore')}
              </button>
            )}
          </div>
        )}
      </div>

      {(selectedCategory || tags.length > 0) && (
        <div className="rounded-xl border border-border/60 bg-muted/40 p-4">
          <div className="mb-3 flex items-center gap-2">
            <Check className="size-4 text-success" />
            <span className="text-sm font-medium text-foreground">{t('summary.title')}</span>
          </div>
          <div className="space-y-1 text-sm text-foreground/80">
            {selectedCategory && (
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">{t('summary.category')}</span>
                <span className="font-medium">{selectedCategory}</span>
              </div>
            )}
            {tags.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">{t('summary.tags')}</span>
                <span className="font-medium">{tags.join(', ')}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
