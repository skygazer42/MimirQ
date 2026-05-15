'use client'

import { useState, useEffect, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
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
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import {
  promptTemplateApi,
  PromptTemplate,
  PromptTemplateCreate,
} from '@/lib/api'
import {
  Plus,
  Edit,
  Trash2,
  Copy,
  Check,
  X,
  Eye,
  Wand2,
  MessageSquare,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { toast } from 'sonner'
import { KgExtractPromptSettings } from '@/components/kg-extract-prompt-settings'
import { KgPredicateOntologySettings } from '@/components/kg-predicate-ontology-settings'
import { AppFrame } from '@/components/app-frame'
import { AnalysisPageShell } from '@/components/ui/analysis-page-shell'
import { PageHeader } from '@/components/ui/page-header'
import { cn } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { EmptyState } from '@/components/ui/empty-state'
import { PageSkeleton } from '@/components/ui/page-skeleton'

export default function PromptsPage() {
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [previewDialogOpen, setPreviewDialogOpen] = useState(false)
  const [editingTemplate, setEditingTemplate] = useState<PromptTemplate | null>(
    null
  )
  const [previewTemplate, setPreviewTemplate] = useState<PromptTemplate | null>(
    null
  )
  const [deleteTemplateTarget, setDeleteTemplateTarget] =
    useState<PromptTemplate | null>(null)

  // Batch selection
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  // Filter & Search
  const [searchQuery, setSearchQuery] = useState('')
  const [categoryFilter, setCategoryFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

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

  const templatesQuery = useQuery<{ total: number; items: PromptTemplate[] }>({
    queryKey: queryKeys.prompts.list({ limit: 100 }),
    queryFn: () => promptTemplateApi.list({ limit: 100 }),
  })
  const templates = useMemo(
    () => templatesQuery.data?.items ?? [],
    [templatesQuery.data?.items]
  )
  const loading = templatesQuery.isLoading
  const templateLoadError = templatesQuery.error
    ? formatApiError(templatesQuery.error, '加载提示词模板失败')
    : ''

  const refreshTemplates = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.prompts.all })

  // Get unique categories
  const categories = useMemo(() => {
    const cats = new Set(
      templates
        .map((t) => t.category)
        .filter(
          (cat): cat is string =>
            typeof cat === 'string' && cat.trim().length > 0
        )
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

  const activeCount = useMemo(
    () => templates.filter((template) => template.is_active).length,
    [templates]
  )
  const inactiveCount = templates.length - activeCount
  const pendingValidationCount = useMemo(
    () => templates.filter((template) => template.usage_count === 0).length,
    [templates]
  )
  const totalPages = Math.max(1, Math.ceil(filteredTemplates.length / pageSize))
  const safeCurrentPage = Math.min(currentPage, totalPages)
  const paginatedTemplates = useMemo(() => {
    const start = (safeCurrentPage - 1) * pageSize
    return filteredTemplates.slice(start, start + pageSize)
  }, [filteredTemplates, pageSize, safeCurrentPage])
  const currentPageIds = useMemo(
    () => paginatedTemplates.map((template) => template.id),
    [paginatedTemplates]
  )
  const allCurrentPageSelected =
    currentPageIds.length > 0 &&
    currentPageIds.every((id) => selectedIds.has(id))

  const activeStatusBadgeClass =
    'rounded-md border-sky-200 bg-sky-50 text-sky-700'
  const inactiveStatusBadgeClass =
    'rounded-md border-slate-200 bg-slate-50 text-slate-600'

  useEffect(() => {
    setCurrentPage(1)
  }, [searchQuery, categoryFilter, statusFilter, pageSize])

  useEffect(() => {
    if (currentPage > totalPages) setCurrentPage(totalPages)
  }, [currentPage, totalPages])

  const formatDateTime = (value?: string) => {
    if (!value) return '-'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return '-'
    const pad = (part: number) => String(part).padStart(2, '0')
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
  }

  // Batch selection handlers
  const handleSelectAll = () => {
    if (allCurrentPageSelected) {
      setSelectedIds((prev) => {
        const next = new Set(prev)
        for (const id of currentPageIds) next.delete(id)
        return next
      })
    } else {
      setSelectedIds((prev) => {
        const next = new Set(prev)
        for (const id of currentPageIds) next.add(id)
        return next
      })
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
      await Promise.all(
        Array.from(selectedIds).map((id) => promptTemplateApi.delete(id))
      )
      toast.success(`已删除 ${selectedIds.size} 个模板`)
      setSelectedIds(new Set())
      await refreshTemplates()
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
      toast.success(
        `已${activate ? '启用' : '停用'} ${selectedIds.size} 个模板`
      )
      setSelectedIds(new Set())
      await refreshTemplates()
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
      await refreshTemplates()
    } catch (error) {
      toast.error(formatApiError(error, '保存失败'))
      console.error(error)
    }
  }

  const handleDelete = async (template: PromptTemplate) => {
    try {
      await promptTemplateApi.delete(template.id)
      toast.success('模板已删除')
      await refreshTemplates()
    } catch (error) {
      toast.error(formatApiError(error, '删除失败'))
      console.error(error)
    }
  }

  const handleDuplicate = async (template: PromptTemplate) => {
    try {
      await promptTemplateApi.duplicate(template.id)
      toast.success('模板已复制')
      await refreshTemplates()
    } catch (error) {
      toast.error(formatApiError(error, '复制失败'))
      console.error(error)
    }
  }

  const handleToggleActive = async (template: PromptTemplate) => {
    try {
      await promptTemplateApi.update(template.id, {
        is_active: !template.is_active,
      })
      toast.success(template.is_active ? '模板已停用' : '模板已启用')
      await refreshTemplates()
    } catch (error) {
      toast.error(formatApiError(error, '更新失败'))
      console.error(error)
    }
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
        <div className="min-h-0 space-y-4 bg-[#f8fafc] px-5 py-4">
          <PageHeader
            title="提示词模板"
            description="维护对话与 KG 系统使用的模板资产；模板为系统提供稳定输出，避免干扰模板的实时编辑。"
            iconImage="prompts"
            icon={Wand2}
            iconColor="text-info"
            badge="模板管理"
            compact
            className="p-0"
          >
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:min-w-[560px]">
              {[
                { label: '总数', value: templates.length, tone: 'slate' },
                { label: '启用', value: activeCount, tone: 'blue' },
                { label: '停用', value: inactiveCount, tone: 'slate' },
                {
                  label: '待验证',
                  value: pendingValidationCount,
                  tone: 'slate',
                },
              ].map((item) => (
                <div
                  key={item.label}
                  className={cn(
                    'rounded-xl border bg-card px-4 py-3 shadow-[0_1px_0_rgba(15,23,42,0.03)]',
                    item.tone === 'blue'
                      ? 'border-blue-200/90'
                      : 'border-slate-200/80'
                  )}
                >
                  <div
                    className={cn(
                      'text-[13px] font-semibold',
                      item.tone === 'blue' ? 'text-blue-600' : 'text-slate-500'
                    )}
                  >
                    {item.label}
                  </div>
                  <div className="mt-3 text-[22px] font-semibold leading-none tabular-nums text-slate-950">
                    {item.value}
                  </div>
                </div>
              ))}
            </div>
          </PageHeader>

          <section className="rounded-xl border border-slate-200/80 bg-card shadow-[0_1px_0_rgba(15,23,42,0.03)]">
            <div className="flex flex-col gap-3 border-b border-slate-200/75 p-4 xl:flex-row xl:items-center">
              <SearchInput
                value={searchQuery}
                onValueChange={setSearchQuery}
                placeholder="搜索模板名称、描述、内容或标签..."
                containerClassName="min-w-0 flex-1"
                inputClassName="h-10 rounded-lg border-slate-200/90 bg-card text-[13px]"
              />
              <div className="grid grid-cols-2 gap-3 md:flex md:items-center">
                <Select
                  value={categoryFilter}
                  onValueChange={setCategoryFilter}
                >
                  <SelectTrigger className="h-10 w-full rounded-lg border-slate-200/90 bg-card text-[13px] md:w-[150px]">
                    <SelectValue placeholder="所有分类" />
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
                  <SelectTrigger className="h-10 w-full rounded-lg border-slate-200/90 bg-card text-[13px] md:w-[150px]">
                    <SelectValue placeholder="所有状态" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">所有状态</SelectItem>
                    <SelectItem value="active">已启用</SelectItem>
                    <SelectItem value="inactive">已停用</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  onClick={handleCreate}
                  className="h-10 gap-1.5 rounded-lg bg-blue-600 px-4 text-[13px] font-semibold text-info-foreground hover:bg-blue-700"
                >
                  <Plus className="size-4" />
                  创建模板
                </Button>
                <Popover>
                  <PopoverTrigger asChild>
                    <Button
                      variant="outline"
                      className="group h-10 justify-between rounded-lg border-slate-200/90 !bg-[linear-gradient(180deg,#ffffff_0%,#f8fbff_100%)] px-2.5 text-left !text-slate-900 shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-colors hover:!bg-[linear-gradient(180deg,#ffffff_0%,#f2f7ff_100%)] hover:!text-slate-900 data-[state=open]:border-blue-200 data-[state=open]:!bg-[linear-gradient(180deg,#ffffff_0%,#f2f7ff_100%)] data-[state=open]:!text-slate-900 md:w-[286px]"
                    >
                      <span className="mr-2 flex size-7 shrink-0 items-center justify-center rounded-lg border border-blue-100 bg-blue-50 text-blue-600 transition-colors group-hover:bg-blue-100/70">
                        <Wand2 className="size-3.5" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex min-w-0 items-center gap-1.5 leading-4">
                          <span className="truncate text-[13px] font-semibold text-slate-900">
                            场景绑定
                          </span>
                          <span className="rounded-full border border-blue-100 bg-blue-50 px-1.5 py-0 text-[9px] font-semibold leading-4 text-blue-600">
                            KG
                          </span>
                        </span>
                        <span className="block truncate text-[11px] font-normal leading-4 text-slate-500">
                          抽取 · 召回 · 关系治理
                        </span>
                      </span>
                      <ChevronDown className="ml-2 size-4 shrink-0 text-slate-400 transition-transform group-data-[state=open]:rotate-180 group-data-[state=open]:text-blue-500" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent
                    align="end"
                    className="max-h-[76vh] w-[540px] overflow-y-auto rounded-2xl border-slate-200 bg-card p-0 shadow-[0_18px_50px_rgba(15,23,42,0.14)]"
                  >
                    <div className="border-b border-slate-100 bg-[linear-gradient(180deg,#f8fbff_0%,#ffffff_100%)] px-4 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="text-[13px] font-semibold text-slate-950">
                            场景绑定
                          </div>
                          <div className="mt-1 text-[12px] leading-5 text-slate-500">
                            把提示词模板绑定到 KG 抽取、对话召回和关系治理。
                          </div>
                        </div>
                        <span className="rounded-full border border-slate-200 bg-card px-2.5 py-1 text-[10px] font-semibold text-slate-500">
                          低频配置
                        </span>
                      </div>
                    </div>
                    <div className="space-y-3 bg-slate-50/45 p-3">
                      <KgExtractPromptSettings templates={templates} />
                      <KgPredicateOntologySettings />
                    </div>
                  </PopoverContent>
                </Popover>
              </div>
            </div>

            {selectedIds.size > 0 ? (
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-sky-100 bg-sky-50/70 px-4 py-2">
                <div className="flex items-center gap-2">
                  <Checkbox checked={true} onCheckedChange={handleSelectAll} />
                  <span className="text-[12px] font-medium text-sky-800">
                    已选择 {selectedIds.size} 个模板
                  </span>
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
                      <Button
                        size="sm"
                        variant="destructive"
                        className="h-7 rounded-md px-2.5 text-[11px]"
                      >
                        <Trash2 className="mr-1 size-3" />
                        批量删除
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>批量删除模板？</AlertDialogTitle>
                        <AlertDialogDescription>
                          你将删除{' '}
                          <span className="font-mono">{selectedIds.size}</span>{' '}
                          个提示词模板。此操作不可撤销。
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction onClick={handleBatchDelete}>
                          删除
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </div>
            ) : null}

            {(() => {
              if (loading) {
                return <PageSkeleton className="py-8" />
              }

              if (templateLoadError) {
                return (
                  <EmptyState
                    icon={MessageSquare}
                    title="提示词模板加载失败"
                    description={templateLoadError}
                  />
                )
              }

              if (filteredTemplates.length === 0) {
                return (
                  <EmptyState
                    icon={MessageSquare}
                    title="暂无提示词模板"
                    description={
                      templates.length === 0
                        ? '还没有创建任何提示词模板。'
                        : '没有找到匹配的模板，请尝试调整筛选条件。'
                    }
                  >
                    {templates.length === 0 ? (
                      <Button
                        onClick={handleCreate}
                        className="h-8 rounded-lg bg-blue-600 px-3 text-xs text-info-foreground hover:bg-blue-700"
                      >
                        <Plus className="mr-2 size-4" />
                        创建第一个模板
                      </Button>
                    ) : null}
                  </EmptyState>
                )
              }

              return (
                <>
                  <div className="overflow-x-auto">
                    <div className="min-w-[1080px]">
                      <div className="grid grid-cols-[40px_minmax(220px,1fr)_78px_62px_130px_136px_350px] items-center border-b border-slate-200/75 bg-slate-50/65 px-4 py-3 text-[12px] font-semibold text-slate-500">
                        <Checkbox
                          checked={allCurrentPageSelected}
                          onCheckedChange={handleSelectAll}
                        />
                        <div>模板</div>
                        <div>分类</div>
                        <div>使用</div>
                        <div>变量</div>
                        <div>更新时间</div>
                        <div>操作</div>
                      </div>
                      <div className="max-h-[calc(100vh-360px)] divide-y divide-slate-100 overflow-y-auto">
                        {paginatedTemplates.map((template) => (
                          <div
                            key={template.id}
                            className={cn(
                              'grid grid-cols-[40px_minmax(220px,1fr)_78px_62px_130px_136px_350px] items-center px-4 py-2 text-[13px] transition-colors hover:bg-slate-50/80',
                              selectedIds.has(template.id) && 'bg-sky-50/60'
                            )}
                          >
                            <div>
                              <Checkbox
                                checked={selectedIds.has(template.id)}
                                onCheckedChange={() =>
                                  handleSelectOne(template.id)
                                }
                              />
                            </div>
                            <button
                              type="button"
                              className="min-w-0 text-left"
                              onClick={() => handlePreview(template)}
                            >
                              <div className="flex min-w-0 items-center gap-2">
                                <span className="truncate font-semibold text-slate-900">
                                  {template.name}
                                </span>
                                <Badge
                                  variant="outline"
                                  className={cn(
                                    'h-5 px-1.5 text-[11px]',
                                    template.is_active
                                      ? activeStatusBadgeClass
                                      : inactiveStatusBadgeClass
                                  )}
                                >
                                  {template.is_active ? '启用' : '停用'}
                                </Badge>
                              </div>
                              <div className="mt-1 truncate text-[12px] text-slate-500">
                                {template.description || '无描述'}
                              </div>
                            </button>
                            <div className="text-slate-500">
                              {template.category || '-'}
                            </div>
                            <div className="tabular-nums text-slate-500">
                              {template.usage_count}
                            </div>
                            <div className="flex min-w-0 flex-wrap gap-1">
                              {template.variables.length > 0 ? (
                                <>
                                  {template.variables
                                    .slice(0, 2)
                                    .map((variable) => (
                                      <Badge
                                        key={variable}
                                        variant="secondary"
                                        className="h-6 rounded-md bg-slate-100 px-2 font-mono text-[11px] font-medium text-slate-700"
                                      >
                                        {`{${variable}}`}
                                      </Badge>
                                    ))}
                                  {template.variables.length > 2 ? (
                                    <span className="text-[11px] text-slate-400">
                                      +{template.variables.length - 2}
                                    </span>
                                  ) : null}
                                </>
                              ) : (
                                <span className="text-slate-400">-</span>
                              )}
                            </div>
                            <div className="tabular-nums text-slate-500">
                              {formatDateTime(template.updated_at)}
                            </div>
                            <div className="flex items-center gap-1.5">
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-7 rounded-lg border-slate-200 px-2 text-[11px]"
                                onClick={() => handlePreview(template)}
                              >
                                <Eye className="mr-1 size-3" />
                                预览
                              </Button>
                              {!template.is_system ? (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="h-7 rounded-lg border-slate-200 px-2 text-[11px]"
                                  onClick={() => handleEdit(template)}
                                >
                                  <Edit className="mr-1 size-3" />
                                  编辑
                                </Button>
                              ) : null}
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-7 rounded-lg border-slate-200 px-2 text-[11px]"
                                onClick={() => handleDuplicate(template)}
                              >
                                <Copy className="mr-1 size-3" />
                                复制
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-7 rounded-lg border-slate-200 px-2 text-[11px]"
                                onClick={() => handleToggleActive(template)}
                              >
                                {template.is_active ? (
                                  <X className="mr-1 size-3" />
                                ) : (
                                  <Check className="mr-1 size-3" />
                                )}
                                {template.is_active ? '停用' : '启用'}
                              </Button>
                              {!template.is_system ? (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="h-7 rounded-lg border-red-100 px-2 text-[11px] text-red-500 hover:bg-red-50 hover:text-red-600"
                                  onClick={() =>
                                    setDeleteTemplateTarget(template)
                                  }
                                >
                                  <Trash2 className="mr-1 size-3" />
                                  删除
                                </Button>
                              ) : null}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="flex flex-col gap-3 border-t border-slate-200/75 px-4 py-3 text-[13px] text-slate-500 md:flex-row md:items-center md:justify-between">
                    <div>共 {filteredTemplates.length} 条</div>
                    <div className="flex flex-wrap items-center justify-end gap-3">
                      <Select
                        value={String(pageSize)}
                        onValueChange={(value) => setPageSize(Number(value))}
                      >
                        <SelectTrigger className="h-9 w-[112px] rounded-lg border-slate-200 bg-card text-[13px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {[10, 20, 50].map((size) => (
                            <SelectItem key={size} value={String(size)}>
                              {size} 条/页
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-9 w-9 rounded-lg border-slate-200 p-0"
                        disabled={safeCurrentPage <= 1}
                        onClick={() =>
                          setCurrentPage((page) => Math.max(1, page - 1))
                        }
                      >
                        <ChevronLeft className="size-4" />
                      </Button>
                      {Array.from(
                        { length: Math.min(4, totalPages) },
                        (_, index) => index + 1
                      ).map((page) => (
                        <Button
                          key={page}
                          variant={
                            safeCurrentPage === page ? 'default' : 'outline'
                          }
                          size="sm"
                          className={cn(
                            'h-9 w-9 rounded-lg p-0 text-[13px]',
                            safeCurrentPage === page
                              ? 'bg-blue-600 text-info-foreground hover:bg-blue-700'
                              : 'border-slate-200 bg-card text-slate-600'
                          )}
                          onClick={() => setCurrentPage(page)}
                        >
                          {page}
                        </Button>
                      ))}
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-9 w-9 rounded-lg border-slate-200 p-0"
                        disabled={safeCurrentPage >= totalPages}
                        onClick={() =>
                          setCurrentPage((page) =>
                            Math.min(totalPages, page + 1)
                          )
                        }
                      >
                        <ChevronRight className="size-4" />
                      </Button>
                      <span>前往</span>
                      <Input
                        value={String(safeCurrentPage)}
                        onChange={(event) => {
                          const value = Number(event.target.value)
                          if (
                            Number.isFinite(value) &&
                            value >= 1 &&
                            value <= totalPages
                          )
                            setCurrentPage(value)
                        }}
                        className="h-9 w-16 rounded-lg border-slate-200 text-center text-[13px]"
                      />
                      <span>页</span>
                    </div>
                  </div>
                </>
              )
            })()}
          </section>
        </div>

        <AlertDialog
          open={Boolean(deleteTemplateTarget)}
          onOpenChange={(open) => {
            if (!open) setDeleteTemplateTarget(null)
          }}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>删除模板？</AlertDialogTitle>
              <AlertDialogDescription>
                你将删除提示词模板{' '}
                <span className="font-mono">
                  {deleteTemplateTarget?.name || '-'}
                </span>
                。此操作不可撤销。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => {
                  const target = deleteTemplateTarget
                  setDeleteTemplateTarget(null)
                  if (target) void handleDelete(target)
                }}
              >
                删除
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* Preview Dialog */}
        <Dialog open={previewDialogOpen} onOpenChange={setPreviewDialogOpen}>
          <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto overscroll-contain rounded-2xl border border-slate-200/80 bg-card no-scrollbar">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                {previewTemplate?.name}
                {previewTemplate?.is_system && (
                  <Badge variant="secondary">系统</Badge>
                )}
                {previewTemplate?.is_active ? (
                  <Badge
                    variant="outline"
                    className={cn('h-5 text-[11px]', activeStatusBadgeClass)}
                  >
                    <Check className="mr-1 size-3" />
                    启用
                  </Badge>
                ) : (
                  <Badge
                    variant="outline"
                    className={cn('h-5 text-[11px]', inactiveStatusBadgeClass)}
                  >
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
              <Button
                variant="outline"
                onClick={() => setPreviewDialogOpen(false)}
              >
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
                创建或编辑提示词模板，支持使用变量如 {'{context}'},{' '}
                {'{question}'}, {'{history}'}
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4">
              <div>
                <Label htmlFor="name">名称 *</Label>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={(e) =>
                    setFormData({ ...formData, name: e.target.value })
                  }
                  placeholder="例如: 法律顾问助手"
                />
              </div>

              <div>
                <Label htmlFor="description">描述</Label>
                <Input
                  id="description"
                  value={formData.description}
                  onChange={(e) =>
                    setFormData({ ...formData, description: e.target.value })
                  }
                  placeholder="简短描述这个模板的用途"
                />
              </div>

              <div>
                <Label htmlFor="category">分类</Label>
                <Input
                  id="category"
                  value={formData.category}
                  onChange={(e) =>
                    setFormData({ ...formData, category: e.target.value })
                  }
                  placeholder="例如: legal, technical, casual"
                  className="h-9"
                />
              </div>

              <div>
                <Label htmlFor="content">模板内容 *</Label>
                <Textarea
                  id="content"
                  value={formData.content}
                  onChange={(e) =>
                    setFormData({ ...formData, content: e.target.value })
                  }
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
                      variables: e.target.value
                        .split(',')
                        .map((v) => v.trim())
                        .filter(Boolean),
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
                      tags: e.target.value
                        .split(',')
                        .map((t) => t.trim())
                        .filter(Boolean),
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
              <Button
                onClick={handleSave}
                disabled={!formData.name || !formData.content}
              >
                保存
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </AnalysisPageShell>
    </AppFrame>
  )
}
