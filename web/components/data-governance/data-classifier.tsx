/**
 * 数据分类归档组件
 * 功能：自动分类、手动分类、标签管理
 */
'use client'

import { useState, useCallback } from 'react'
import { FolderTree, Tag, Plus, X, Sparkles, Check, Folder, FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

interface DataClassifierProps {
  content: string
  initialCategory?: string | null
  initialTags?: string[]
  onClassify: (category: string, tags: string[]) => void
}

// 预设分类
const PRESET_CATEGORIES = [
    { id: 'technical', label: '技术文档', icon: FileText, tone: 'info', keywords: ['api', 'sdk', '开发', '代码', '配置'] },
    { id: 'product', label: '产品文档', icon: FileText, tone: 'success', keywords: ['产品', '功能', '特性', '版本', '发布'] },
    { id: 'business', label: '业务文档', icon: Folder, tone: 'primary', keywords: ['业务', '流程', '规范', '制度'] },
    { id: 'legal', label: '法律文档', icon: Folder, tone: 'destructive', keywords: ['合同', '协议', '法律', '条款', '合规'] },
    { id: 'hr', label: '人事文档', icon: Folder, tone: 'warning', keywords: ['人事', '招聘', '员工', '薪酬', '培训'] },
    { id: 'finance', label: '财务文档', icon: Folder, tone: 'warning', keywords: ['财务', '报表', '预算', '发票', '费用'] },
    { id: 'other', label: '其他', icon: Folder, tone: 'neutral', keywords: [] },
]

type CategoryTone = typeof PRESET_CATEGORIES[number]['tone']

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

// 推荐标签
const SUGGESTED_TAGS = [
  '重要', '公开', '内部', '机密', '待审核', '已归档',
  'v1.0', 'v2.0', '最新版', '历史版',
  'FAQ', '教程', '指南', '参考',
  '紧急', '长期', '临时',
]

export function DataClassifier({ content, initialCategory = null, initialTags = [], onClassify }: Readonly<DataClassifierProps>) {
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
          <FolderTree className="w-5 h-5 text-primary" />
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
              <div className="w-3.5 h-3.5 border-2 border-muted-foreground/30 border-t-primary rounded-full motion-safe:animate-spin motion-reduce:animate-none" />
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
            const tone = getCategoryToneStyles(category.tone)

	            return (
	              <button
	                key={category.id}
	                onClick={() => handleSelectCategory(category.id)}
	                className={cn(
	                  "flex items-center gap-2 p-3 rounded-xl border text-left transition-colors duration-200 motion-reduce:transition-none focus-ring",
	                  isSelected
	                    ? tone.selected
	                    : "bg-muted border-border hover:bg-muted"
	                )}
	              >
                <div className={cn(
                  "w-8 h-8 rounded-lg flex items-center justify-center",
                  tone.iconWrap,
                )}>
                  <Icon className={cn("w-4 h-4", tone.icon)} />
                </div>
                <span className={cn(
                  "text-sm font-medium",
                  isSelected ? tone.text : "text-foreground/80"
                )}>
                  {category.label}
                </span>
                {isSelected && (
                  <Check className={cn("w-4 h-4 ml-auto", tone.icon)} />
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
                className="inline-flex items-center gap-1 px-2.5 py-1 bg-secondary/60 text-foreground border border-border/60 text-sm rounded-lg"
              >
                <Tag className="w-3 h-3" />
                {tag}
                <button
                  type="button"
                  onClick={() => handleRemoveTag(tag)}
                  aria-label={`移除标签 ${tag}`}
                  className="ml-1 text-muted-foreground hover:text-destructive"
                >
                  <X className="w-3 h-3" aria-hidden="true" />
                </button>
              </span>
            ))}
          </div>
        )}

        {/* 添加标签输入 */}
        <div className="flex gap-2">
          <Input
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
            className="flex-1"
          />
          <Button
            onClick={() => handleAddTag(newTag)}
            disabled={!newTag || tags.includes(newTag)}
            size="sm"
            aria-label={newTag ? `添加标签 ${newTag}` : '添加标签'}
          >
            <Plus className="w-4 h-4" aria-hidden="true" />
          </Button>
        </div>

        {/* 推荐标签 */}
        {(suggestedTags.length > 0 || SUGGESTED_TAGS.length > 0) && (
          <div className="space-y-2">
            {suggestedTags.length > 0 && (
              <div className="flex items-center gap-2 text-xs text-info">
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
                      "inline-flex items-center gap-1 px-2 py-1 text-xs rounded-lg border transition-colors duration-200 motion-reduce:transition-none",
                      (() => {
    if (isAdded) {
        return "bg-primary/15 text-primary border-primary/20 cursor-default";
    }
    else if (isRecommended) {
            return "bg-info/10 text-info border-info/20 hover:bg-info/15";
        }
        else {
            return "bg-muted text-muted-foreground border-border hover:bg-accent/40 hover:text-foreground";
        }
})(),
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
        <div className="bg-muted/40 border border-border/60 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <Check className="w-4 h-4 text-success" />
            <span className="text-sm font-medium text-foreground">归档信息</span>
          </div>
          <div className="space-y-1 text-sm text-foreground/80">
            {selectedCategory && (
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">分类:</span>
                <span className="font-medium">{selectedCategory}</span>
              </div>
            )}
            {tags.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">标签:</span>
                <span className="font-medium">{tags.join(', ')}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
