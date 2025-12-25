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
  { id: 'entity', label: '实体', icon: Hash, color: 'blue', description: '命名实体（人名、地名、组织）' },
  { id: 'keyword', label: '关键词', icon: Highlighter, color: 'green', description: '重要关键词' },
  { id: 'sensitive', label: '敏感信息', icon: Shield, color: 'red', description: '需要脱敏的信息' },
  { id: 'custom', label: '自定义', icon: Type, color: 'purple', description: '自定义标签' },
] as const

type AnnotationTypeId = typeof ANNOTATION_TYPES[number]['id']

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
                  "px-1 rounded cursor-pointer transition-all hover:opacity-80",
                  type.color === 'blue' && "bg-blue-100 text-blue-800 border border-blue-200",
                  type.color === 'green' && "bg-green-100 text-green-800 border border-green-200",
                  type.color === 'red' && "bg-red-100 text-red-800 border border-red-200 line-through",
                  type.color === 'purple' && "bg-purple-100 text-purple-800 border border-purple-200",
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
        <Tag className="w-5 h-5 text-purple-600" />
        <h3 className="font-bold text-gray-900">数据标注</h3>
      </div>

      {/* 标注类型选择 */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-gray-500">选择标注类型</div>
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
                    ? `bg-${type.color}-50 border-${type.color}-300 ring-1 ring-${type.color}-200`
                    : "bg-gray-50 border-gray-200 hover:bg-gray-100"
                )}
              >
                <div className={cn(
                  "w-7 h-7 rounded-lg flex items-center justify-center",
                  type.color === 'blue' && "bg-blue-100",
                  type.color === 'green' && "bg-green-100",
                  type.color === 'red' && "bg-red-100",
                  type.color === 'purple' && "bg-purple-100",
                )}>
                  <Icon className={cn("w-3.5 h-3.5", `text-${type.color}-600`)} />
                </div>
                <div className="flex-1">
                  <div className={cn(
                    "text-sm font-medium",
                    isSelected ? `text-${type.color}-900` : "text-gray-700"
                  )}>
                    {type.label}
                  </div>
                  <div className="text-xs text-gray-400">{count} 个</div>
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {/* 自定义标签输入 */}
      {selectedType === 'custom' && (
        <div>
          <input
            type="text"
            placeholder="输入自定义标签名称..."
            value={customLabel}
            onChange={(e) => setCustomLabel(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
          />
        </div>
      )}

      {/* 选区标注操作 */}
      {selection ? (
        <div className="bg-purple-50 border border-purple-200 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <Search className="w-4 h-4 text-purple-600" />
            <span className="text-sm font-medium text-purple-700">已选中文本</span>
          </div>
          <div className="bg-white p-2 rounded border border-purple-100 mb-3">
            <div className="text-sm text-gray-700 line-clamp-2">
              {selection.text}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              onClick={handleAddAnnotation}
              size="sm"
              className="flex-1 gap-1.5 bg-purple-600 hover:bg-purple-700"
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
            "w-full gap-2",
            isSelecting && "bg-purple-600 hover:bg-purple-700"
          )}
        >
          <Highlighter className="w-4 h-4" />
          {isSelecting ? '请在右侧选择文本...' : '开始选中文本标注'}
        </Button>
      )}

      {/* 已有标注列表 */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-gray-500">已有标注 ({localAnnotations.length})</div>

        {ANNOTATION_TYPES.map((type) => {
          const items = annotationsByType[type.id]
          const Icon = type.icon
          const isExpanded = expandedTypes.has(type.id)

          if (items.length === 0) return null

          return (
            <div key={type.id} className="border border-gray-200 rounded-xl overflow-hidden">
              <button
                onClick={() => toggleExpandedType(type.id)}
                className="w-full flex items-center justify-between p-3 hover:bg-gray-50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Icon className={cn("w-4 h-4", `text-${type.color}-500`)} />
                  <span className="text-sm font-medium text-gray-700">{type.label}</span>
                  <span className={cn(
                    "text-xs px-1.5 py-0.5 rounded-full",
                    `bg-${type.color}-100`,
                    `text-${type.color}-700`
                  )}>
                    {items.length}
                  </span>
                </div>
                {isExpanded ? (
                  <ChevronDown className="w-4 h-4 text-gray-400" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-gray-400" />
                )}
              </button>

              {isExpanded && (
                <div className="p-3 pt-0 border-t border-gray-100 space-y-2">
                  {items.map((anno) => (
                    <div
                      key={anno.id}
                      className="flex items-center justify-between p-2 bg-gray-50 rounded-lg"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="text-xs text-gray-400">
                          位置: {anno.start} - {anno.end}
                        </div>
                        <div className="text-sm text-gray-700 truncate">
                          {anno.text}
                        </div>
                      </div>
                      <Button
                        onClick={() => handleDeleteAnnotation(anno.id)}
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0 text-gray-400 hover:text-red-500"
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
          <div className="text-center py-8 text-gray-400">
            <Tag className="w-10 h-10 mx-auto mb-2 opacity-30" />
            <p className="text-sm">暂无标注</p>
            <p className="text-xs mt-1">选中文本后点击上方按钮添加</p>
          </div>
        )}
      </div>
    </div>
  )
}
