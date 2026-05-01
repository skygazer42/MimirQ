'use client'

import { useState, useEffect, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { SearchInput } from '@/components/ui/search-input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { promptTemplateApi, PromptTemplate, PromptTemplateCreate } from '@/lib/api'
import { Plus, Edit, Trash2, Copy, Check, X, Eye, Filter, Wand2, MessageSquare, ListChecks, CircleCheckBig, CircleOff } from 'lucide-react'
import { toast } from 'sonner'
import { KgExtractPromptSettings } from '@/components/kg-extract-prompt-settings'
import { KgPredicateOntologySettings } from '@/components/kg-predicate-ontology-settings'
import { AppFrame } from '@/components/app-frame'
import { AnalysisPageShell } from '@/components/ui/analysis-page-shell'
import { cn, detachPromise } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { EmptyState } from '@/components/ui/empty-state'
import { PageSkeleton } from '@/components/ui/page-skeleton'
import { PromptRagOperationsPanel } from '@/components/prompts/prompt-rag-operations-panel'

export default function PromptsPage() {
  const [templates, setTemplates] = useState<PromptTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [previewDialogOpen, setPreviewDialogOpen] = useState(false)
  const [editingTemplate, setEditingTemplate] = useState<PromptTemplate | null>(null)
  const [previewTemplate, setPreviewTemplate] = useState<PromptTemplate | null>(null)

  // Batch selection
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  // Filter & Search
  const [searchQuery, setSearchQuery] = useState('')
  const [categoryFilter, setCategoryFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<string>('all')

  // Form state
  const [formData, setFormData] = useState<PromptTemplateCreate>({
    name: '',
    description: '',
    content: '',
    variables: [],
    category: '',
    tags: [],
    is_active: true,
  })

  // Load templates
  useEffect(() => {
    loadTemplates()
  }, [])

  const loadTemplates = async () => {
    try {
      setLoading(true)
      const response = await promptTemplateApi.list({ limit: 100 })
      setTemplates(response.items)
    } catch (error) {
      toast.error(formatApiError(error, '加载提示词模板失败'))
      console.error(error)
    } finally {
      setLoading(false)
    }
  }

  // Get unique categories
  const categories = useMemo(() => {
    const cats = new Set(
      templates
        .map((t) => t.category)
        .filter((cat): cat is string => typeof cat === 'string' && cat.trim().length > 0)
    )
    return Array.from(cats)
  }, [templates])

  // Filtered templates
  const filteredTemplates = useMemo(() => {
    return templates.filter((template) => {
      // Search filter
      if (searchQuery) {
        const query = searchQuery.toLowerCase()
        const matchesSearch =
          template.name.toLowerCase().includes(query) ||
          template.description?.toLowerCase().includes(query) ||
          template.content.toLowerCase().includes(query) ||
          template.tags.some((tag) => tag.toLowerCase().includes(query))
        if (!matchesSearch) return false
      }

      // Category filter
      if (categoryFilter !== 'all' && template.category !== categoryFilter) {
        return false
      }

      // Status filter
      if (statusFilter === 'active' && !template.is_active) return false
      if (statusFilter === 'inactive' && template.is_active) return false

      return true
    })

}, [templates, searchQuery, categoryFilter, statusFilter])

const activeCount = useMemo(() => templates.filter((template) => template.is_active).length, [templates])
const filteredActiveCount = useMemo(
  () => filteredTemplates.filter((template) => template.is_active).length,
  [filteredTemplates]
)
const inactiveCount = templates.length - activeCount
const filteredInactiveCount = filteredTemplates.length - filteredActiveCount

const activeStatusBadgeClass = 'rounded-md border-sky-200 bg-sky-50 text-sky-700'
const inactiveStatusBadgeClass = 'rounded-md border-slate-200 bg-slate-50 text-slate-600'

// Batch selection handlers
  const handleSelectAll = () => {
    if (selectedIds.size === filteredTemplates.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(filteredTemplates.map((t) => t.id)))
    }
  }

  const handleSelectOne = (id: string) => {
    const newSelected = new Set(selectedIds)
    if (newSelected.has(id)) {
      newSelected.delete(id)
    } else {
      newSelected.add(id)
    }
    setSelectedIds(newSelected)
  }

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return

    try {
      await Promise.all(Array.from(selectedIds).map((id) => promptTemplateApi.delete(id)))
      toast.success(`已删除 ${selectedIds.size} 个模板`)
      setSelectedIds(new Set())
      loadTemplates()
    } catch (error) {
      toast.error(formatApiError(error, '批量删除失败'))
      console.error(error)
    }
  }

  const handleBatchActivate = async (activate: boolean) => {
    if (selectedIds.size === 0) return

    try {
      await Promise.all(
        Array.from(selectedIds).map((id) =>
          promptTemplateApi.update(id, { is_active: activate })
        )
      )
      toast.success(`已${activate ? '启用' : '停用'} ${selectedIds.size} 个模板`)
      setSelectedIds(new Set())
      loadTemplates()
    } catch (error) {
      toast.error(formatApiError(error, '批量操作失败'))
      console.error(error)
    }
  }

  const handleCreate = () => {
    setEditingTemplate(null)
    setFormData({
      name: '',
      description: '',
      content: '',
      variables: [],
      category: '',
      tags: [],
      is_active: true,
    })
    setDialogOpen(true)
  }

  const handleEdit = (template: PromptTemplate) => {
    setEditingTemplate(template)
    setFormData({
      name: template.name,
      description: template.description || '',
      content: template.content,
      variables: template.variables,
      category: template.category || '',
      tags: template.tags,
      is_active: template.is_active,
    })
    setDialogOpen(true)
  }

  const handlePreview = (template: PromptTemplate) => {
    setPreviewTemplate(template)
    setPreviewDialogOpen(true)
  }

  const handleSave = async () => {
    try {
      if (editingTemplate) {
        await promptTemplateApi.update(editingTemplate.id, formData)
        toast.success('模板已更新')
      } else {
        await promptTemplateApi.create(formData)
        toast.success('模板已创建')
      }
      setDialogOpen(false)
      loadTemplates()
    } catch (error) {
      toast.error(formatApiError(error, '保存失败'))
      console.error(error)
    }
  }

  const handleDelete = async (template: PromptTemplate) => {
    try {
      await promptTemplateApi.delete(template.id)
      toast.success('模板已删除')
      loadTemplates()
    } catch (error) {
      toast.error(formatApiError(error, '删除失败'))
      console.error(error)
    }
  }

  const handleDuplicate = async (template: PromptTemplate) => {
    try {
      await promptTemplateApi.duplicate(template.id)
      toast.success('模板已复制')
      loadTemplates()
    } catch (error) {
      toast.error(formatApiError(error, '复制失败'))
      console.error(error)
    }
  }

  const handleToggleActive = async (template: PromptTemplate) => {
    try {
      await promptTemplateApi.update(template.id, { is_active: !template.is_active })
      toast.success(template.is_active ? '模板已停用' : '模板已启用')
      loadTemplates()
    } catch (error) {
      toast.error(formatApiError(error, '更新失败'))
      console.error(error)
    }
  }

  const stopTemplateCardClick = (event: React.MouseEvent<HTMLElement>) => {
    event.stopPropagation()
  }

  return (
    <AppFrame>
      <AnalysisPageShell
        title="提示词模板"
        badge="提示词"
        icon={Wand2}
        iconColor="text-primary"
        description="创建和管理您的 RAG 对话提示词模板"
        size="full"
        showHeader={false}
        bodyGutter="none"
        bodyClassName="!pb-0"
        bodyContainerClassName="max-w-none"
      >

<div className="overflow-hidden rounded-2xl border border-slate-200/80 bg-[linear-gradient(180deg,#f8fafc_0%,#ffffff_22%)] shadow-[0_1px_0_rgba(15,23,42,0.04)]">
  <div className="flex flex-col gap-2.5 border-b border-slate-200/80 bg-muted/35 px-4 py-3 lg:flex-row lg:items-end lg:justify-between">
    <div className="min-w-0">
      <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">提示词中心 · 管理工作台</div>
      <div className="mt-1 text-[15px] font-semibold tracking-[-0.01em] text-foreground">提示词模板配置与批量运营</div>
      <p className="mt-1 text-[12px] leading-5 text-muted-foreground">统一管理模板、启停状态、分类与变量，面向生产 RAG 场景做高密度维护。</p>
    </div>
    <div className="flex flex-wrap items-center gap-2 text-[11px]">
      <Badge variant="outline" className="rounded-md border-slate-200/80 bg-card text-[11px] text-slate-600"><ListChecks className="mr-1 size-3" />总模板 {templates.length}</Badge>
      <Badge variant="outline" className={cn('text-[11px]', activeStatusBadgeClass)}><CircleCheckBig className="mr-1 size-3" />已启用 {activeCount}</Badge>
      <Badge variant="outline" className={cn('text-[11px]', inactiveStatusBadgeClass)}><CircleOff className="mr-1 size-3" />已停用 {inactiveCount}</Badge>
      <Badge variant="outline" className="rounded-md border-slate-200/80 bg-card text-[11px] text-slate-600"><Filter className="mr-1 size-3" />筛选后 {filteredTemplates.length}</Badge>
    </div>
  </div>

  <div className="space-y-4 p-4">
    <section className="rounded-xl border border-slate-200/80 bg-card p-3">
      <div className="grid gap-2 lg:grid-cols-[minmax(280px,1fr)_170px_170px_auto]">
        <SearchInput
          value={searchQuery}
          onValueChange={setSearchQuery}
          placeholder="搜索模板名称、描述、内容或标签..."
          containerClassName="w-full"
          inputClassName="h-9 text-[12px]"
        />
        <Select value={categoryFilter} onValueChange={setCategoryFilter}>
          <SelectTrigger className="h-9 w-full rounded-lg border-slate-200/80 bg-card text-[12px]">
            <Filter className="mr-2 size-4" />
            <SelectValue placeholder="筛选分类" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">所有分类</SelectItem>
            {categories.map((cat) => (
              <SelectItem key={cat} value={cat}>
                {cat}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="h-9 w-full rounded-lg border-slate-200/80 bg-card text-[12px]">
            <SelectValue placeholder="筛选状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">所有状态</SelectItem>
            <SelectItem value="active">已启用</SelectItem>
            <SelectItem value="inactive">已停用</SelectItem>
          </SelectContent>
        </Select>
        <Button onClick={handleCreate} className="h-9 gap-1.5 rounded-lg bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary/90">
          <Plus className="size-4" />
          创建模板
        </Button>
      </div>
    </section>

    <section className="rounded-xl border border-slate-200/80 bg-card p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-slate-200/70 pb-2 text-[11px] text-muted-foreground">
        <Badge variant="outline" className="rounded-md border-slate-200/80 bg-slate-50 text-[11px] text-slate-600">高级配置</Badge>
        <span>KG 抽取相关提示配置与本体约束</span>
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <KgExtractPromptSettings templates={templates} />
        <KgPredicateOntologySettings />
      </div>
    </section>

    <PromptRagOperationsPanel />

    {selectedIds.size > 0 && (
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-sky-200/80 bg-sky-50/70 px-3 py-2">
        <div className="flex items-center gap-2">
          <Checkbox checked={true} onCheckedChange={handleSelectAll} />
          <span className="text-[12px] font-medium text-sky-800">已选择 {selectedIds.size} 个模板</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Button
            size="sm"
            variant="outline"
            className="h-7 rounded-md border-sky-200 bg-card px-2.5 text-[11px] text-sky-700 hover:bg-sky-50"
            onClick={() => handleBatchActivate(true)}
          >
            批量启用
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-7 rounded-md border-slate-200 bg-card px-2.5 text-[11px] text-slate-700 hover:bg-slate-50"
            onClick={() => handleBatchActivate(false)}
          >
            批量停用
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button size="sm" variant="destructive" className="h-7 rounded-md px-2.5 text-[11px]">
                <Trash2 className="mr-1 size-3" />
                批量删除
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>批量删除模板？</AlertDialogTitle>
                <AlertDialogDescription>
                  你将删除 <span className="font-mono">{selectedIds.size}</span> 个提示词模板。此操作不可撤销。
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>取消</AlertDialogCancel>
                <AlertDialogAction onClick={handleBatchDelete}>删除</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>
    )}

    {(() => {
      if (loading) {
        return <PageSkeleton className="py-8" />
      }

      if (filteredTemplates.length === 0) {
        return (
          <EmptyState
            icon={MessageSquare}
            title="暂无提示词模板"
            description={templates.length === 0 ? '还没有创建任何提示词模板。' : '没有找到匹配的模板，请尝试调整筛选条件。'}
          >
            {templates.length === 0 ? (
              <Button onClick={handleCreate} className="h-8 rounded-lg bg-primary px-3 text-xs text-primary-foreground hover:bg-primary/90">
                <Plus className="mr-2 size-4" />
                创建第一个模板
              </Button>
            ) : null}
          </EmptyState>
        )
      }

      return (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200/80 bg-card px-3 py-2">
            <label className="inline-flex items-center gap-2 text-[12px] text-slate-700">
              <Checkbox
                checked={selectedIds.size === filteredTemplates.length && filteredTemplates.length > 0}
                onCheckedChange={handleSelectAll}
              />
              全选
            </label>
            <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
              <Badge variant="outline" className={cn('text-[11px]', activeStatusBadgeClass)}>已启用 {filteredActiveCount}</Badge>
              <Badge variant="outline" className={cn('text-[11px]', inactiveStatusBadgeClass)}>已停用 {filteredInactiveCount}</Badge>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {filteredTemplates.map((template) => (
              <Card
                key={template.id}
                role="button"
                tabIndex={0}
                aria-label={`预览模板：${template.name}`}
                onClick={() => handlePreview(template)}
                onKeyDown={(event) => {
                  if (event.currentTarget !== event.target) return
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    handlePreview(template)
                  }
                }}
                className={cn(
                  'relative cursor-pointer rounded-xl border border-slate-200/80 bg-card shadow-none transition-colors hover:border-sky-300/80 focus-ring',
                  selectedIds.has(template.id) && 'border-sky-300 bg-sky-50/40'
                )}
              >
                <CardHeader className="p-3 pb-2">
                  <div className="flex items-start gap-2.5">
                    <Checkbox
                      checked={selectedIds.has(template.id)}
                      onCheckedChange={() => handleSelectOne(template.id)}
                      onClick={(event) => event.stopPropagation()}
                      className="mt-0.5"
                    />
                    <div className="min-w-0 flex-1 space-y-1.5">
                      <CardTitle className="flex flex-wrap items-center gap-1.5 text-[13px] font-semibold leading-5 text-slate-900">
                        <span className="truncate">{template.name}</span>
                        {template.is_system ? <Badge variant="secondary" className="h-5 rounded-md text-[11px]">系统</Badge> : null}
                        <Badge variant="outline" className={cn('h-5 text-[11px]', template.is_active ? activeStatusBadgeClass : inactiveStatusBadgeClass)}>
                          {template.is_active ? (
                            <>
                              <Check className="mr-1 size-3" />
                              启用
                            </>
                          ) : (
                            <>
                              <X className="mr-1 size-3" />
                              停用
                            </>
                          )}
                        </Badge>
                      </CardTitle>

                      <div className="flex flex-wrap items-center gap-1.5">
                        {template.category ? (
                          <Badge variant="outline" className="h-5 rounded-md border-slate-200/80 bg-slate-50 text-[11px] text-slate-600">
                            {template.category}
                          </Badge>
                        ) : null}
                        <Badge variant="outline" className="h-5 rounded-md border-slate-200/80 bg-card text-[11px] text-slate-500">
                          使用 {template.usage_count}
                        </Badge>
                      </div>

                      <CardDescription className="line-clamp-2 text-[12px] leading-5 text-slate-500">
                        {template.description || '无描述'}
                      </CardDescription>
                    </div>
                  </div>
                </CardHeader>

                <CardContent className="space-y-2.5 p-3 pt-0">
                  <div className="space-y-1">
                    <div className="text-[11px] font-medium text-slate-500">变量</div>
                    <div className="flex min-h-6 flex-wrap gap-1">
                      {template.variables.length > 0 ? (
                        template.variables.map((variable) => (
                          <Badge key={variable} variant="secondary" className="h-5 rounded-md bg-slate-100 px-1.5 font-mono text-[11px] text-slate-700">
                            {`{${variable}}`}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-[11px] text-muted-foreground">无</span>
                      )}
                    </div>
                  </div>

                  {template.tags.length > 0 ? (
                    <div className="space-y-1">
                      <div className="text-[11px] font-medium text-slate-500">标签</div>
                      <div className="flex flex-wrap gap-1">
                        {template.tags.map((tag) => (
                          <Badge key={tag} variant="outline" className="h-5 rounded-md border-slate-200/80 bg-card px-1.5 text-[11px] text-slate-600">
                            {tag}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  <div className="flex flex-wrap gap-1.5 border-t border-slate-200/80 pt-2">
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 rounded-md border-slate-200/80 px-2 text-[11px]"
                      onClick={(event) => {
                        stopTemplateCardClick(event)
                        handlePreview(template)
                      }}
                    >
                      <Eye className="mr-1 size-3" />
                      预览
                    </Button>

                    {!template.is_system ? (
                      <>
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 rounded-md border-slate-200/80 px-2 text-[11px]"
                          onClick={(event) => {
                            stopTemplateCardClick(event)
                            handleEdit(template)
                          }}
                        >
                          <Edit className="mr-1 size-3" />
                          编辑
                        </Button>

                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button size="sm" variant="outline" className="h-7 rounded-md border-slate-200/80 px-2 text-[11px]" onClick={stopTemplateCardClick}>
                              <Trash2 className="mr-1 size-3" />
                              删除
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>删除模板？</AlertDialogTitle>
                              <AlertDialogDescription>
                                你将删除提示词模板 <span className="font-mono">{template.name}</span>。此操作不可撤销。
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>取消</AlertDialogCancel>
                              <AlertDialogAction onClick={() => detachPromise(handleDelete(template))}>删除</AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </>
                    ) : null}

                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 rounded-md border-slate-200/80 px-2 text-[11px]"
                      onClick={(event) => {
                        stopTemplateCardClick(event)
                        handleDuplicate(template)
                      }}
                    >
                      <Copy className="mr-1 size-3" />
                      复制
                    </Button>

                    <Button
                      size="sm"
                      variant={template.is_active ? 'outline' : 'default'}
                      className={cn(
                        'h-7 rounded-md px-2 text-[11px] font-medium',
                        template.is_active
                          ? 'border-slate-200/80 bg-card text-slate-700 hover:bg-slate-50'
                          : 'bg-primary text-primary-foreground hover:bg-primary/90'
                      )}
                      onClick={(event) => {
                        stopTemplateCardClick(event)
                        handleToggleActive(template)
                      }}
                    >
                      {template.is_active ? '停用' : '启用'}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )
    })()}
  </div>
</div>


      {/* Preview Dialog */}
      <Dialog open={previewDialogOpen} onOpenChange={setPreviewDialogOpen}>
        <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto overscroll-contain rounded-2xl border border-slate-200/80 bg-card no-scrollbar">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {previewTemplate?.name}
              {previewTemplate?.is_system && <Badge variant="secondary">系统</Badge>}
              {previewTemplate?.is_active ? (
                <Badge variant="outline" className={cn('h-5 text-[11px]', activeStatusBadgeClass)}>
                  <Check className="mr-1 size-3" />
                  启用
                </Badge>
              ) : (
                <Badge variant="outline" className={cn('h-5 text-[11px]', inactiveStatusBadgeClass)}>
                  <X className="mr-1 size-3" />
                  停用
                </Badge>
              )}
            </DialogTitle>
            <DialogDescription>
              {previewTemplate?.description || '无描述'}
            </DialogDescription>
          </DialogHeader>

          {previewTemplate && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-sm font-medium">分类</Label>
                  <p className="text-sm text-muted-foreground mt-1">
                    {previewTemplate.category || '无'}
                  </p>
                </div>
                <div>
                  <Label className="text-sm font-medium">使用次数</Label>
                  <p className="text-sm text-muted-foreground mt-1">
                    {previewTemplate.usage_count}
                  </p>
                </div>
              </div>

              <div>
                <Label className="text-sm font-medium">支持的变量</Label>
                <div className="flex flex-wrap gap-1 mt-2">
                  {previewTemplate.variables.length > 0 ? (
                    previewTemplate.variables.map((v) => (
                      <Badge key={v} variant="secondary">
                        {`{${v}}`}
                      </Badge>
                    ))
                  ) : (
                    <span className="text-sm text-muted-foreground">无</span>
                  )}
                </div>
              </div>

              {previewTemplate.tags.length > 0 && (
                <div>
                  <Label className="text-sm font-medium">标签</Label>
                  <div className="flex flex-wrap gap-1 mt-2">
                    {previewTemplate.tags.map((tag) => (
                      <Badge key={tag} variant="outline">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <Label className="text-sm font-medium">模板内容</Label>
                <div className="mt-2 p-4 bg-muted/60 rounded-lg">
                  <pre className="text-sm whitespace-pre-wrap font-mono">
                    {previewTemplate.content}
                  </pre>
                </div>
              </div>
            </div>
          )}

          <DialogFooter>
            {previewTemplate && !previewTemplate.is_system && (
              <Button
                variant="outline"
                onClick={() => {
                  setPreviewDialogOpen(false)
                  handleEdit(previewTemplate)
                }}
              >
                <Edit className="w-4 h-4 mr-2" />
                编辑
              </Button>
            )}
            <Button variant="outline" onClick={() => setPreviewDialogOpen(false)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto overscroll-contain rounded-2xl border border-slate-200/80 bg-card no-scrollbar">
          <DialogHeader>
            <DialogTitle className="text-[15px] font-semibold">
              {editingTemplate ? '编辑模板' : '创建新模板'}
            </DialogTitle>
            <DialogDescription>
              创建或编辑提示词模板，支持使用变量如 {'{context}'}, {'{question}'}, {'{history}'}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div>
              <Label htmlFor="name">名称 *</Label>
              <Input
                id="name"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder="例如: 法律顾问助手"
              />
            </div>

            <div>
              <Label htmlFor="description">描述</Label>
              <Input
                id="description"
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                placeholder="简短描述这个模板的用途"
              />
            </div>

            <div>
              <Label htmlFor="category">分类</Label>
              <Input
                id="category"
                value={formData.category}
                onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                placeholder="例如: legal, technical, casual"
                className="h-9"
              />
            </div>

            <div>
              <Label htmlFor="content">模板内容 *</Label>
              <Textarea
                id="content"
                value={formData.content}
                onChange={(e) => setFormData({ ...formData, content: e.target.value })}
                placeholder="输入提示词模板内容，使用 {context}, {question}, {history} 等变量"
                className="min-h-[300px] font-mono text-sm"
              />
            </div>

            <div>
              <Label htmlFor="variables">支持的变量 (逗号分隔)</Label>
              <Input
                id="variables"
                value={formData.variables?.join(', ')}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    variables: e.target.value.split(',').map((v) => v.trim()).filter(Boolean),
                  })
                }
                placeholder="context, question, history, format_instructions"
              />
            </div>

            <div>
              <Label htmlFor="tags">标签 (逗号分隔)</Label>
              <Input
                id="tags"
                value={formData.tags?.join(', ')}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    tags: e.target.value.split(',').map((t) => t.trim()).filter(Boolean),
                  })
                }
                placeholder="expert, concise, formal"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={handleSave} disabled={!formData.name || !formData.content}>
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      </AnalysisPageShell>
    </AppFrame>
  )
}
