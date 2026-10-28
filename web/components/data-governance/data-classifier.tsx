'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChevronRight, FileText, Folder, FolderTree, Loader2, Plus, X } from '@/components/icons'
import styles from './governance-inbox.module.css'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { pipelineApi } from '@/lib/api'
import { reportClientWarning } from '@/lib/client-logging'
import type { AutoDocumentTag } from '@/types'

interface DataClassifierProps {
  content: string
  initialCategory?: string | null
  initialTags?: string[]
  onClassify: (category: string, tags: string[]) => void
}

type CategoryId = 'technical' | 'product' | 'business' | 'legal' | 'hr' | 'finance' | 'other'

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

function dedupeStrings(values: string[]): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const value of values) {
    const normalized = String(value || '').trim()
    if (!normalized || seen.has(normalized)) continue
    seen.add(normalized)
    result.push(normalized)
  }
  return result
}

function getTagText(tag: AutoDocumentTag): string {
  return String(tag.value || '').trim()
}

function isLongTag(tag: string): boolean {
  return tag.length > 32 || /[\r\n]/.test(tag)
}

function displayTag(tag: string): string {
  const sensitivityLabels: Record<string, string> = { internal: '内部', public: '公开', restricted: '受限', confidential: '机密' }
  return sensitivityLabels[tag] ?? tag
}

function selectCategoryTag(tags: AutoDocumentTag[]): AutoDocumentTag | undefined {
  const preferredTypes: AutoDocumentTag['type'][] = ['category', 'domain', 'industry', 'doc_type', 'topic']
  for (const type of preferredTypes) {
    const match = tags.find((tag) => tag.type === type && getTagText(tag) && !isLongTag(getTagText(tag)))
    if (match) return match
  }
  return undefined
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
      })),
    [t]
  )
  const suggestedTagLabels = t.raw('suggestedTags') as string[]
  const [selectedCategory, setSelectedCategory] = useState<string | null>(initialCategory)
  const [tags, setTags] = useState<string[]>(initialTags)
  const [newTag, setNewTag] = useState('')
  const [isAutoClassifying, setIsAutoClassifying] = useState(false)
  const [suggestedTags, setSuggestedTags] = useState<string[]>([])
  const shortTags = tags.filter(tag => !isLongTag(tag))
  const longTags = tags.filter(isLongTag)
  const availableSuggestions = dedupeStrings([...suggestedTags, ...suggestedTagLabels])
    .filter(tag => !tags.some(item => displayTag(item) === displayTag(tag)) && !isLongTag(tag))
  const contentRef = useRef(content)
  useEffect(() => { contentRef.current = content }, [content])
  useEffect(() => { setSelectedCategory(initialCategory) }, [initialCategory])
  useEffect(() => { setTags(initialTags) }, [initialTags])

  const handleAutoClassify = useCallback(async () => {
    const source = String(content || '')
    if (!source.trim() || isAutoClassifying) {
      toast.warning(t('auto.empty'))
      return
    }

    setIsAutoClassifying(true)
    try {
      const response = await pipelineApi.autoAnnotations({
        text: source,
        mode: 'document_focus',
        providers: ['cpu'],
        enable_keywords: true,
        enable_entities: true,
        enable_sensitive: false,
        keyword_provider: 'simple',
        keyword_top_k: 12,
        max_annotations: 60,
      })
      if (contentRef.current !== source) return
      const documentTags = response.document_tags || []
      const categoryTag = selectCategoryTag(documentTags)
      const nextCategory = categoryTag ? getTagText(categoryTag) : t('categories.other.label')
      const backendSuggestedTags = dedupeStrings(documentTags.map(getTagText))
      const nextTags = dedupeStrings([...tags, ...backendSuggestedTags])

      setSelectedCategory(nextCategory)
      setSuggestedTags(backendSuggestedTags)
      setTags(nextTags)
      onClassify(nextCategory, nextTags)

      if (backendSuggestedTags.length > 0) {
        toast.success(t('auto.success', { count: backendSuggestedTags.length }))
      } else {
        toast.info(t('auto.noTags'))
      }
    } catch (error) {
      reportClientWarning('Backend auto classification failed', error)
      toast.error(t('auto.failed'))
    } finally {
      setIsAutoClassifying(false)
    }
  }, [content, isAutoClassifying, onClassify, t, tags])

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

  return (
    <>
      <div className={styles.toolLine}>
        <div className={styles.toolIdentity}><strong>分类与标签</strong><span>{tags.length} 个标签</span></div>
        <div className={styles.toolActions}><Button onClick={() => void handleAutoClassify()} disabled={isAutoClassifying || !content.trim()}>{isAutoClassifying ? <Loader2 className={styles.spinner} /> : <FolderTree className="size-4" />}{isAutoClassifying ? '正在分类…' : '自动分类'}</Button></div>
      </div>
      <div className={styles.toolBody}>
        <div className={styles.classifierForm}>
          <div className={`${styles.fieldGroup} ${styles.classifierCategory}`}>
            <label htmlFor="governance-category">文档分类</label>
            <select className={styles.fieldControl} id="governance-category" value={selectedCategory || ''} disabled={isAutoClassifying} onChange={event => { setSelectedCategory(event.target.value); onClassify(event.target.value, tags) }}>
              <option value="">未分类</option>{selectedCategory && !categories.some(category => category.label === selectedCategory) && <option value={selectedCategory}>{selectedCategory}</option>}
              {categories.map(category => <option key={category.id} value={category.label}>{category.label}</option>)}
            </select>
          </div>
          <form className={styles.classifierTagForm} onSubmit={event => { event.preventDefault(); if (newTag.trim()) handleAddTag(newTag.trim()) }}>
            <label htmlFor="governance-new-tag" className={styles.fieldLabel}>文档标签</label>
            <div className={styles.classifierTagEntry}>
              <input className={styles.fieldControl} id="governance-new-tag" value={newTag} onChange={event => setNewTag(event.target.value)} placeholder="输入标签名称" disabled={isAutoClassifying} />
              <Button variant="outline" type="submit" disabled={!newTag.trim() || isAutoClassifying}><Plus className="size-4" />添加</Button>
            </div>
          </form>
        </div>
        {shortTags.length > 0 && <ul className={`${styles.tags} ${styles.classifierTags}`} aria-label="已添加标签">
          {shortTags.map(tag => <li className={styles.tag} key={tag}>
            <span title={displayTag(tag) !== tag ? tag : undefined}>{displayTag(tag)}</span>
            <button type="button" aria-label={'删除标签 ' + tag} disabled={isAutoClassifying} onClick={() => handleRemoveTag(tag)}><X /></button>
          </li>)}
        </ul>}
        {longTags.length > 0 || availableSuggestions.length > 0 ? <div className={styles.annotationDetails}>
          {longTags.length > 0 && <details className={styles.annotationDisclosure}>
            <summary><ChevronRight aria-hidden="true" /><span>长文本标签</span><span className={styles.annotationCount}>{longTags.length}</span></summary>
            <ul className={styles.classifierLongTags} aria-label="长文本标签">
              {longTags.map(tag => <li key={tag}>
                <p>{tag}</p>
                <Button size="icon" variant="ghost" className={styles.annotationDelete} aria-label={'删除标签 ' + tag} disabled={isAutoClassifying} onClick={() => handleRemoveTag(tag)}><X className="size-4" /></Button>
              </li>)}
            </ul>
          </details>}
          {availableSuggestions.length > 0 && <details className={styles.annotationDisclosure}>
            <summary><ChevronRight aria-hidden="true" /><span>推荐标签</span><span className={styles.annotationCount}>{availableSuggestions.length}</span></summary>
            <ul className={styles.classifierSuggestions} aria-label="推荐标签">
              {availableSuggestions.map(tag => <li key={tag}><button type="button" disabled={isAutoClassifying} aria-label={'添加推荐标签 ' + tag} onClick={() => handleAddTag(tag)}><Plus aria-hidden="true" />{displayTag(tag)}</button></li>)}
            </ul>
          </details>}
        </div> : null}
      </div>
    </>
  )
}
