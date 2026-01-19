/**
 * 数据分类归档组件
 * 功能：自动分类、手动分类、标签管理
 */
'use client'

import { useState, useCallback, useMemo } from 'react'
import {
  FolderTree,
  Tag,
  Plus,
  X,
  Search,
  Sparkles,
  Check,
  ChevronDown,
  ChevronRight,
  Folder,
  FolderOpen,
  FileText,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface DataClassifierProps {
  content: string
  initialCategory?: string | null
  initialTags?: string[]
  onClassify: (category: string, tags: string[]) => void
}

// 预设分类
const PRESET_CATEGORIES = [
  { id: 'technical', label: '技术文档', icon: FileText, color: 'blue', keywords: ['api', 'sdk', '开发', '代码', '配置'] },
  { id: 'product', label: '产品文档', icon: FileText, color: 'green', keywords: ['产品', '功能', '特性', '版本', '发布'] },
  { id: 'business', label: '业务文档', icon: Folder, color: 'purple', keywords: ['业务', '流程', '规范', '制度'] },
  { id: 'legal', label: '法律文档', icon: Folder, color: 'red', keywords: ['合同', '协议', '法律', '条款', '合规'] },
  { id: 'hr', label: '人事文档', icon: Folder, color: 'orange', keywords: ['人事', '招聘', '员工', '薪酬', '培训'] },
  { id: 'finance', label: '财务文档', icon: Folder, color: 'yellow', keywords: ['财务', '报表', '预算', '发票', '费用'] },
  { id: 'other', label: '其他', icon: Folder, color: 'gray', keywords: [] },
] as const

// 推荐标签
const SUGGESTED_TAGS = [
  '重要', '公开', '内部', '机密', '待审核', '已归档',
  'v1.0', 'v2.0', '最新版', '历史版',
  'FAQ', '教程', '指南', '参考',
  '紧急', '长期', '临时',
]

export function DataClassifier({ content, initialCategory = null, initialTags = [], onClassify }: DataClassifierProps) {
  const [selectedCategory, setSelectedCategory] = useState<string | null>(initialCategory)
  const [tags, setTags] = useState<string[]>(initialTags)
  const [newTag, setNewTag] = useState('')
  const [isAutoClassifying, setIsAutoClassifying] = useState(false)
  const [suggestedTags, setSuggestedTags] = useState<string[]>([])
  const [showAllTags, setShowAllTags] = useState(false)

  // 自动分类
  const handleAutoClassify = useCallback(async () => {
    setIsAutoClassifying(true)

    // 模拟 AI 分类
    await new Promise((resolve) => setTimeout(resolve, 1000))

    const contentLower = content.toLowerCase()

    // 简单关键词匹配分类
    let bestMatch = 'other'
    let maxScore = 0

    PRESET_CATEGORIES.forEach((cat) => {
      const score = cat.keywords.reduce((sum, kw) => {
        return sum + (contentLower.includes(kw.toLowerCase()) ? 1 : 0)
      }, 0)
      if (score > maxScore) {
        maxScore = score
        bestMatch = cat.id
      }
    })

    const category = PRESET_CATEGORIES.find(c => c.id === bestMatch)!
    setSelectedCategory(category.label)

    // 推荐标签
    const recommendations: string[] = []

    if (contentLower.includes('重要') || contentLower.includes('必须')) recommendations.push('重要')
    if (contentLower.includes('faq') || contentLower.includes('常见')) recommendations.push('FAQ')
    if (contentLower.includes('教程') || contentLower.includes('指南')) recommendations.push('教程')
    if (contentLower.includes('api')) recommendations.push('API')
    if (contentLower.includes('版本') || contentLower.includes('v1')) recommendations.push('v1.0')

    setSuggestedTags(recommendations)

    setIsAutoClassifying(false)
    onClassify(category.label, tags)
  }, [content, tags, onClassify])

  // 添加标签
  const handleAddTag = useCallback((tag: string) => {
    if (tag && !tags.includes(tag)) {
      const updated = [...tags, tag]
      setTags(updated)
      onClassify(selectedCategory || '', updated)
    }
    setNewTag('')
  }, [tags, selectedCategory, onClassify])

  // 删除标签
  const handleRemoveTag = useCallback((tag: string) => {
    const updated = tags.filter((t) => t !== tag)
    setTags(updated)
    onClassify(selectedCategory || '', updated)
  }, [tags, selectedCategory, onClassify])

  // 选择分类
  const handleSelectCategory = useCallback((categoryId: string) => {
    const category = PRESET_CATEGORIES.find(c => c.id === categoryId)!
    setSelectedCategory(category.label)
    onClassify(category.label, tags)
  }, [tags, onClassify])

  // 当前显示的标签
  const displayTags = showAllTags ? SUGGESTED_TAGS : SUGGESTED_TAGS.slice(0, 8)

  return (
    <div className="p-6 space-y-6">
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FolderTree className="w-5 h-5 text-orange-600" />
          <h3 className="font-bold text-foreground">分类归档</h3>
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
              <div className="w-3.5 h-3.5 border-2 border-border border-t-orange-500 rounded-full animate-spin" />
              分析中...
            </>
          ) : (
            <>
              <Sparkles className="w-3.5 h-3.5" />
              AI 分类
            </>
          )}
        </Button>
      </div>

      {/* 分类选择 */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-muted-foreground">文档分类</div>
        <div className="grid grid-cols-2 gap-2">
          {PRESET_CATEGORIES.map((category) => {
            const Icon = category.icon
            const isSelected = selectedCategory === category.label

            return (
              <button
                key={category.id}
                onClick={() => handleSelectCategory(category.id)}
                className={cn(
                  "flex items-center gap-2 p-3 rounded-xl border text-left transition-all",
                  isSelected
                    ? `bg-${category.color}-50 border-${category.color}-300 ring-1 ring-${category.color}-200`
                    : "bg-muted border-border hover:bg-muted"
                )}
              >
                <div className={cn(
                  "w-8 h-8 rounded-lg flex items-center justify-center",
                  category.color === 'blue' && "bg-blue-100",
                  category.color === 'green' && "bg-green-100",
                  category.color === 'purple' && "bg-teal-100",
                  category.color === 'red' && "bg-red-100",
                  category.color === 'orange' && "bg-orange-100",
                  category.color === 'yellow' && "bg-yellow-100",
                  category.color === 'gray' && "bg-muted",
                )}>
                  <Icon className={cn("w-4 h-4", `text-${category.color}-600`)} />
                </div>
                <span className={cn(
                  "text-sm font-medium",
                  isSelected ? `text-${category.color}-900` : "text-foreground/80"
                )}>
                  {category.label}
                </span>
                {isSelected && (
                  <Check className={cn("w-4 h-4 ml-auto", `text-${category.color}-600`)} />
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* 标签管理 */}
      <div className="space-y-3">
        <div className="text-xs font-medium text-muted-foreground">标签</div>

        {/* 已选标签 */}
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-2 p-3 bg-muted rounded-xl">
            {tags.map((tag) => (
              <span
                key={tag}
                className="inline-flex items-center gap-1 px-2.5 py-1 bg-orange-100 text-orange-700 text-sm rounded-lg"
              >
                <Tag className="w-3 h-3" />
                {tag}
                <button
                  onClick={() => handleRemoveTag(tag)}
                  className="ml-1 hover:text-orange-900"
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}
          </div>
        )}

        {/* 添加标签输入 */}
        <div className="flex gap-2">
          <input
            type="text"
            placeholder="输入新标签..."
            value={newTag}
            onChange={(e) => setNewTag(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                handleAddTag(newTag)
              }
            }}
            className="flex-1 px-3 py-2 text-sm border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent"
          />
          <Button
            onClick={() => handleAddTag(newTag)}
            disabled={!newTag || tags.includes(newTag)}
            size="sm"
            className="bg-orange-600 hover:bg-orange-700"
          >
            <Plus className="w-4 h-4" />
          </Button>
        </div>

        {/* 推荐标签 */}
        {(suggestedTags.length > 0 || SUGGESTED_TAGS.length > 0) && (
          <div className="space-y-2">
            {suggestedTags.length > 0 && (
              <div className="flex items-center gap-2 text-xs text-orange-600">
                <Sparkles className="w-3.5 h-3.5" />
                <span>AI 推荐标签</span>
              </div>
            )}

            <div className="flex flex-wrap gap-1.5">
              {(suggestedTags.length > 0 ? suggestedTags : displayTags).map((tag) => {
                const isAdded = tags.includes(tag)
                const isRecommended = suggestedTags.includes(tag)

                return (
                  <button
                    key={tag}
                    onClick={() => !isAdded && handleAddTag(tag)}
                    disabled={isAdded}
                    className={cn(
                      "inline-flex items-center gap-1 px-2 py-1 text-xs rounded-lg transition-all",
                      isAdded
                        ? "bg-orange-500 text-white"
                        : isRecommended
                          ? "bg-orange-100 text-orange-700 hover:bg-orange-200"
                          : "bg-muted text-muted-foreground hover:bg-border",
                      )}
                  >
                    {isRecommended && !isAdded && <Sparkles className="w-3 h-3" />}
                    {tag}
                  </button>
                )
              })}
            </div>

            {SUGGESTED_TAGS.length > 8 && !showAllTags && suggestedTags.length === 0 && (
              <button
                onClick={() => setShowAllTags(true)}
                className="text-xs text-muted-foreground hover:text-muted-foreground"
              >
                显示更多...
              </button>
            )}
          </div>
        )}
      </div>

      {/* 分类信息摘要 */}
      {(selectedCategory || tags.length > 0) && (
        <div className="bg-gradient-to-r from-orange-500/10 to-amber-500/10 border border-orange-500/30 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <Check className="w-4 h-4 text-orange-600" />
            <span className="text-sm font-medium text-orange-900">归档信息</span>
          </div>
          <div className="space-y-1 text-sm text-orange-800">
            {selectedCategory && (
              <div className="flex items-center gap-2">
                <span className="text-orange-600">分类:</span>
                <span className="font-medium">{selectedCategory}</span>
              </div>
            )}
            {tags.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-orange-600">标签:</span>
                <span className="font-medium">{tags.join(', ')}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
