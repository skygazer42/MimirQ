/**
 * 数据标注组件
 * 功能：文本标注、实体识别、关键词标记、敏感信息打码
 */
'use client'

import { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import {
  Tag,
  Plus,
  X,
  Hash,
  Shield,
  Type,
  Highlighter,
  Search,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'
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

// 标注类型配置
const ANNOTATION_TYPES = [
  { id: 'entity', label: '实体', icon: Hash, tone: 'info', description: '命名实体（人名、地名、组织）' },
  { id: 'keyword', label: '关键词', icon: Highlighter, tone: 'success', description: '重要关键词' },
  { id: 'sensitive', label: '敏感信息', icon: Shield, tone: 'destructive', description: '需要脱敏的信息' },
  { id: 'custom', label: '自定义', icon: Type, tone: 'primary', description: '自定义标签' },
] as const

type AnnotationTypeId = typeof ANNOTATION_TYPES[number]['id']
type AnnotationTone = typeof ANNOTATION_TYPES[number]['tone']

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

export function DataAnnotator({ content, annotations = [], onAnnotate }: DataAnnotatorProps) {
  const [selectedType, setSelectedType] = useState<AnnotationTypeId>('keyword')
  const [customLabel, setCustomLabel] = useState('')
  const [isSelecting, setIsSelecting] = useState(false)
  const [selection, setSelection] = useState<{ start: number; end: number; text: string } | null>(null)
  const [localAnnotations, setLocalAnnotations] = useState<Annotation[]>(annotations)
  const [expandedTypes, setExpandedTypes] = useState<Set<AnnotationTypeId>>(new Set())

  const contentRef = useRef<HTMLDivElement>(null)

  // 按类型分组统计
  const annotationsByType = useMemo(() => {
    const grouped: Record<AnnotationTypeId, Annotation[]> = {
      entity: [],
      keyword: [],
      sensitive: [],
      custom: [],
    }
    localAnnotations.forEach((a) => {
      grouped[a.type].push(a)
    })
    return grouped
  }, [localAnnotations])

  // 处理文本选择
  const handleMouseUp = useCallback(() => {
    if (!isSelecting) return

    const selection = window.getSelection()
    if (!selection || selection.rangeCount === 0) {
      setSelection(null)
      return
    }

    const range = selection.getRangeAt(0)
    const text = range.toString().trim()

    if (!text) {
      setSelection(null)
      return
    }

    // 获取在原文中的位置
    const preCaretRange = range.cloneRange()
    preCaretRange.selectNodeContents(contentRef.current!)
    preCaretRange.setEnd(range.startContainer, range.startOffset)
    const start = preCaretRange.toString().length

    const end = start + text.length

    setSelection({ start, end, text })
    window.getSelection()?.removeAllRanges()
  }, [isSelecting])

  // 添加标注
  const handleAddAnnotation = useCallback(() => {
    if (!selection) return

    const label = selectedType === 'custom' ? customLabel || '自定义' : ANNOTATION_TYPES.find(t => t.id === selectedType)!.label

    const newAnnotation: Annotation = {
      id: `anno-${Date.now()}`,
      text: selection.text,
      type: selectedType,
      label,
      start: selection.start,
      end: selection.end,
    }

    const updated = [...localAnnotations, newAnnotation]
    setLocalAnnotations(updated)
    onAnnotate(updated)
    setSelection(null)
    setCustomLabel('')
  }, [selection, selectedType, customLabel, localAnnotations, onAnnotate])

  // 删除标注
  const handleDeleteAnnotation = useCallback((id: string) => {
    const updated = localAnnotations.filter((a) => a.id !== id)
    setLocalAnnotations(updated)
    onAnnotate(updated)
  }, [localAnnotations, onAnnotate])

  // 切换展开类型
  const toggleExpandedType = useCallback((type: AnnotationTypeId) => {
    setExpandedTypes((prev) => {
      const next = new Set(prev)
      if (next.has(type)) {
        next.delete(type)
      } else {
        next.add(type)
      }
      return next
    })
  }, [])

  // 渲染带高亮的文本
  const renderHighlightedText = useCallback(() => {
    if (!content) return null

    // 按位置排序
    const sorted = [...localAnnotations].sort((a, b) => a.start - b.start)

    const segments: Array<{ text: string; annotation?: Annotation }> = []
    let lastIndex = 0

    sorted.forEach((anno) => {
      if (anno.start > lastIndex) {
        segments.push({ text: content.slice(lastIndex, anno.start) })
      }
      segments.push({ text: content.slice(anno.start, anno.end), annotation: anno })
      lastIndex = anno.end
    })

    if (lastIndex < content.length) {
      segments.push({ text: content.slice(lastIndex) })
    }

    return (
      <div
        ref={contentRef}
        onMouseUp={handleMouseUp}
        className="text-sm leading-relaxed whitespace-pre-wrap"
      >
        {segments.map((seg, idx) => {
          if (seg.annotation) {
            const type = ANNOTATION_TYPES.find(t => t.id === seg.annotation!.type)!
            return (
              <mark
                key={idx}
                className={cn(
                  "px-1 rounded cursor-pointer transition-opacity hover:opacity-80 motion-reduce:transition-none",
                  getToneStyles(type.tone).mark,
                  seg.annotation.type === 'sensitive' && "line-through",
                )}
                title={seg.annotation.label}
              >
                {seg.text}
              </mark>
            )
          }
          return <span key={idx}>{seg.text}</span>
        })}
      </div>
    )
  }, [content, localAnnotations, handleMouseUp])

  const typeConfig = ANNOTATION_TYPES.find(t => t.id === selectedType)!

  return (
    <div className="p-6 space-y-6">
      {/* 标题 */}
      <div className="flex items-center gap-2">
        <Tag className="w-5 h-5 text-primary" />
        <h3 className="font-bold text-foreground">数据标注</h3>
      </div>

      {/* 标注类型选择 */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-muted-foreground">选择标注类型</div>
        <div className="grid grid-cols-2 gap-2">
          {ANNOTATION_TYPES.map((type) => {
            const Icon = type.icon
            const isSelected = selectedType === type.id
            const count = annotationsByType[type.id].length

            return (
              <button
                key={type.id}
                onClick={() => setSelectedType(type.id)}
                className={cn(
                  "flex items-center gap-2 p-2.5 rounded-lg border text-left transition-all",
                  isSelected
                    ? getToneStyles(type.tone).selected
                    : "bg-muted border-border hover:bg-muted"
                )}
              >
                <div className={cn(
                  "w-7 h-7 rounded-lg flex items-center justify-center",
                  getToneStyles(type.tone).iconWrap,
                )}>
                  <Icon className={cn("w-3.5 h-3.5", getToneStyles(type.tone).icon)} />
                </div>
                <div className="flex-1">
                  <div className={cn(
                    "text-sm font-medium",
                    isSelected ? getToneStyles(type.tone).text : "text-foreground/80"
                  )}>
                    {type.label}
                  </div>
                  <div className="text-xs text-muted-foreground">{count} 个</div>
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {/* 自定义标签输入 */}
      {selectedType === 'custom' && (
        <div>
          <Input
            type="text"
            placeholder="输入自定义标签名称..."
            value={customLabel}
            onChange={(e) => setCustomLabel(e.target.value)}
            className="w-full"
          />
        </div>
      )}

      {/* 选区标注操作 */}
      {selection ? (
        <div className="bg-primary/10 border border-primary/20 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <Search className="w-4 h-4 text-primary" />
            <span className="text-sm font-medium text-primary">已选中文本</span>
          </div>
          <div className="bg-card p-2 rounded border border-primary/20 mb-3">
            <div className="text-sm text-foreground/80 line-clamp-2">
              {selection.text}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              onClick={handleAddAnnotation}
              size="sm"
              className="flex-1 gap-1.5"
            >
              <Plus className="w-3.5 h-3.5" />
              添加{typeConfig.label}标注
            </Button>
            <Button
              onClick={() => setSelection(null)}
              variant="outline"
              size="sm"
            >
              取消
            </Button>
          </div>
        </div>
      ) : (
        <Button
          onClick={() => setIsSelecting(!isSelecting)}
          variant={isSelecting ? "default" : "outline"}
          size="sm"
          className={cn(
            "w-full gap-2"
          )}
        >
          <Highlighter className="w-4 h-4" />
          {isSelecting ? '请在右侧选择文本...' : '开始选中文本标注'}
        </Button>
      )}

      {/* 已有标注列表 */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-muted-foreground">已有标注 ({localAnnotations.length})</div>

        {ANNOTATION_TYPES.map((type) => {
          const items = annotationsByType[type.id]
          const Icon = type.icon
          const isExpanded = expandedTypes.has(type.id)

          if (items.length === 0) return null

          return (
            <div key={type.id} className="border border-border rounded-xl overflow-hidden">
              <button
                onClick={() => toggleExpandedType(type.id)}
                className="w-full flex items-center justify-between p-3 hover:bg-muted transition-colors motion-reduce:transition-none"
              >
                <div className="flex items-center gap-2">
                  <Icon className={cn("w-4 h-4", getToneStyles(type.tone).icon)} />
                  <span className="text-sm font-medium text-foreground/80">{type.label}</span>
                  <span className={cn(
                    "text-xs px-1.5 py-0.5 rounded-full border",
                    getToneStyles(type.tone).pill
                  )}>
                    {items.length}
                  </span>
                </div>
                {isExpanded ? (
                  <ChevronDown className="w-4 h-4 text-muted-foreground" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-muted-foreground" />
                )}
              </button>

              {isExpanded && (
                <div className="p-3 pt-0 border-t border-border space-y-2">
                  {items.map((anno) => (
                    <div
                      key={anno.id}
                      className="flex items-center justify-between p-2 bg-muted rounded-lg"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="text-xs text-muted-foreground">
                          位置: {anno.start} - {anno.end}
                        </div>
                        <div className="text-sm text-foreground/80 truncate">
                          {anno.text}
                        </div>
                      </div>
                      <Button
                        onClick={() => handleDeleteAnnotation(anno.id)}
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                      >
                        <X className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}

        {localAnnotations.length === 0 && (
          <div className="text-center py-8 text-muted-foreground">
            <Tag className="w-10 h-10 mx-auto mb-2 opacity-30" />
            <p className="text-sm">暂无标注</p>
            <p className="text-xs mt-1">选中文本后点击上方按钮添加</p>
          </div>
        )}
      </div>
    </div>
  )
}
