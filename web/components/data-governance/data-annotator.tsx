/**
 * 鏁版嵁鏍囨敞缁勪欢
 * 鍔熻兘锛氭枃鏈爣娉ㄣ€佸疄浣撹瘑鍒€佸叧閿瘝鏍囪銆佹晱鎰熶俊鎭墦鐮?
 */
'use client'

import { useEffect, useMemo, useState } from 'react'
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
  type LucideIcon,
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

type AnnotationTypeId = Annotation['type']
type AnnotationTone = 'info' | 'success' | 'destructive' | 'primary'
type AnnotationTypeConfig = {
  id: AnnotationTypeId
  label: string
  icon: LucideIcon
  tone: AnnotationTone
  description: string
}

// 鏍囨敞绫诲瀷閰嶇疆
const ANNOTATION_TYPES: AnnotationTypeConfig[] = [
  { id: 'entity', label: '实体', icon: Hash, tone: 'info', description: '命名实体，例如人名、地名、组织' },
  { id: 'keyword', label: '关键词', icon: Highlighter, tone: 'success', description: '重要关键词' },
  { id: 'sensitive', label: '敏感信息', icon: Shield, tone: 'destructive', description: '需要脱敏的信息' },
  { id: 'custom', label: '自定义', icon: Type, tone: 'primary', description: '自定义标签' },
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
  const [selectedType, setSelectedType] = useState<AnnotationTypeId>('keyword')
  const [customLabel, setCustomLabel] = useState('')
  const [isSelecting, setIsSelecting] = useState(false)
  const [selection, setSelection] = useState<{ start: number; end: number; text: string } | null>(null)
  const [localAnnotations, setLocalAnnotations] = useState<Annotation[]>(annotations)
  const [expandedTypes, setExpandedTypes] = useState<Set<AnnotationTypeId>>(new Set())


  // 鎸夌被鍨嬪垎缁勭粺璁?
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


  const typeConfig = ANNOTATION_TYPES.find(t => t.id === selectedType)!

  useEffect(() => {
    setLocalAnnotations(annotations)
  }, [annotations])

  const handleAddAnnotation = () => {
    if (!selection) return

    const label = selectedType === 'custom' ? customLabel.trim() : typeConfig.label
    if (!label) return

    const nextAnnotation: Annotation = {
      id: globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${selection.start}-${selection.end}`,
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
    <div className="p-6 space-y-6">
      {/* 鏍囬 */}
      <div className="flex items-center gap-2">
        <Tag className="w-5 h-5 text-primary" />
        <h3 className="font-bold text-foreground">鏁版嵁鏍囨敞</h3>
      </div>

      {/* 鏍囨敞绫诲瀷閫夋嫨 */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-muted-foreground">閫夋嫨鏍囨敞绫诲瀷</div>
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
	                  "flex items-center gap-2 p-2.5 rounded-lg border text-left transition-colors duration-200 motion-reduce:transition-none focus-ring",
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

      {/* 鑷畾涔夋爣绛捐緭鍏?*/}
      {selectedType === 'custom' && (
        <div>
          <Input
            type="text"
            placeholder="杈撳叆鑷畾涔夋爣绛惧悕绉?.."
            value={customLabel}
            onChange={(e) => setCustomLabel(e.target.value)}
            className="w-full"
          />
        </div>
      )}

      {/* 閫夊尯鏍囨敞鎿嶄綔 */}
      {selection ? (
        <div className="bg-primary/10 border border-primary/20 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <Search className="w-4 h-4 text-primary" />
            <span className="text-sm font-medium text-primary">宸查€変腑鏂囨湰</span>
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
              娣诲姞{typeConfig.label}鏍囨敞
            </Button>
            <Button
              onClick={() => setSelection(null)}
              variant="outline"
              size="sm"
            >
              鍙栨秷
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
          {isSelecting ? '璇峰湪鍙充晶閫夋嫨鏂囨湰...' : '寮€濮嬮€変腑鏂囨湰鏍囨敞'}
        </Button>
      )}

      {/* 宸叉湁鏍囨敞鍒楄〃 */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-muted-foreground">宸叉湁鏍囨敞 ({localAnnotations.length})</div>

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
                          浣嶇疆: {anno.start} - {anno.end}
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
                        aria-label={`删除 ${type.label} 标注 ${anno.start}-${anno.end}`}
                      >
                        <X className="w-3.5 h-3.5" aria-hidden="true" />
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
            <p className="text-sm">鏆傛棤鏍囨敞</p>
            <p className="text-xs mt-1">选中文本后点击上方按钮添加</p>
          </div>
        )}
      </div>
    </div>
  )
}
