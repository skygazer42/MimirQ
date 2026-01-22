'use client'

import { useState, useEffect, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
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
import { promptTemplateApi, PromptTemplate, PromptTemplateCreate } from '@/lib/api-client'
import { Plus, Edit, Trash2, Copy, Check, X, Eye, Search, Filter, Wand2 } from 'lucide-react'
import { toast } from 'sonner'
import { KgExtractPromptSettings } from '@/components/kg-extract-prompt-settings'
import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { cn } from '@/lib/utils'

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
      toast.error('加载提示词模板失败')
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
    if (!confirm(`确定要删除 ${selectedIds.size} 个模板吗？`)) return

    try {
      await Promise.all(Array.from(selectedIds).map((id) => promptTemplateApi.delete(id)))
      toast.success(`已删除 ${selectedIds.size} 个模板`)
      setSelectedIds(new Set())
      loadTemplates()
    } catch (error) {
      toast.error('批量删除失败')
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
      toast.error('批量操作失败')
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
      toast.error('保存失败')
      console.error(error)
    }
  }

  const handleDelete = async (template: PromptTemplate) => {
    if (!confirm(`确定要删除模板 "${template.name}" 吗？`)) return

    try {
      await promptTemplateApi.delete(template.id)
      toast.success('模板已删除')
      loadTemplates()
    } catch (error) {
      toast.error('删除失败')
      console.error(error)
    }
  }

  const handleDuplicate = async (template: PromptTemplate) => {
    try {
      await promptTemplateApi.duplicate(template.id)
      toast.success('模板已复制')
      loadTemplates()
    } catch (error) {
      toast.error('复制失败')
      console.error(error)
    }
  }

  const handleToggleActive = async (template: PromptTemplate) => {
    try {
      await promptTemplateApi.update(template.id, { is_active: !template.is_active })
      toast.success(template.is_active ? '模板已停用' : '模板已启用')
      loadTemplates()
    } catch (error) {
      toast.error('更新失败')
      console.error(error)
    }
  }

  return (
    <AppFrame>
      <PageScaffold
        title="提示词模板"
        badge="PROMPTS"
        icon={Wand2}
        iconColor="text-indigo-600 dark:text-indigo-400"
        description="创建和管理您的 RAG 对话提示词模板"
        actions={
          <Button onClick={handleCreate} className="gap-2">
            <Plus className="w-4 h-4" />
            创建模板
          </Button>
        }
      >
        <div className="mb-6">
          <KgExtractPromptSettings templates={templates} />
        </div>

          {/* Filters & Search */}
          <div className="mb-6 flex flex-col sm:flex-row gap-4">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="搜索模板名称、描述、内容或标签..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10"
              />
            </div>
            <Select value={categoryFilter} onValueChange={setCategoryFilter}>
              <SelectTrigger className="w-[180px]">
                <Filter className="w-4 h-4 mr-2" />
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
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="筛选状态" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">所有状态</SelectItem>
                <SelectItem value="active">已启用</SelectItem>
                <SelectItem value="inactive">已停用</SelectItem>
              </SelectContent>
            </Select>
          </div>

      {/* Batch Actions */}
      {selectedIds.size > 0 && (
        <div className="mb-4 p-4 bg-muted rounded-lg flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Checkbox checked={true} onCheckedChange={handleSelectAll} />
            <span className="text-sm font-medium">已选择 {selectedIds.size} 个模板</span>
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => handleBatchActivate(true)}>
              批量启用
            </Button>
            <Button size="sm" variant="outline" onClick={() => handleBatchActivate(false)}>
              批量停用
            </Button>
            <Button size="sm" variant="destructive" onClick={handleBatchDelete}>
              <Trash2 className="w-3 h-3 mr-1" />
              批量删除
            </Button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-center py-12">加载中...</div>
      ) : filteredTemplates.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            {templates.length === 0 ? (
              <>
                <p>还没有提示词模板</p>
                <Button onClick={handleCreate} className="mt-4">
                  创建第一个模板
                </Button>
              </>
            ) : (
              <p>没有找到匹配的模板</p>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {/* Select All */}
          <div className="flex items-center gap-2 px-2">
            <Checkbox
              checked={selectedIds.size === filteredTemplates.length && filteredTemplates.length > 0}
              onCheckedChange={handleSelectAll}
            />
            <span className="text-sm text-muted-foreground">全选</span>
          </div>

          {/* Template Grid */}
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {filteredTemplates.map((template) => (
              <Card
                key={template.id}
                role="button"
                tabIndex={0}
                aria-label={`预览模板：${template.name}`}
                onClick={() => handlePreview(template)}
                onKeyDown={(e) => {
                  if (e.currentTarget !== e.target) return
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    handlePreview(template)
                  }
                }}
                className={cn(
                  "relative cursor-pointer transition-colors hover:border-primary focus-ring",
                  selectedIds.has(template.id) && "border-primary bg-muted/50 dark:bg-muted/60"
                )}
              >
                <CardHeader>
                  <div className="flex items-start gap-3">
                    <Checkbox
                      checked={selectedIds.has(template.id)}
                      onCheckedChange={() => handleSelectOne(template.id)}
                      onClick={(e) => e.stopPropagation()}
                    />
                    <div className="flex-1">
                      <CardTitle className="flex items-center gap-2 flex-wrap">
                        <span className="truncate">{template.name}</span>
                        {template.is_system && (
                          <Badge variant="secondary">系统</Badge>
                        )}
                        {template.is_active ? (
                          <Badge variant="success">
                            <Check className="w-3 h-3 mr-1" />
                            启用
                          </Badge>
                        ) : (
                          <Badge variant="soft">
                            <X className="w-3 h-3 mr-1" />
                            停用
                          </Badge>
                        )}
                      </CardTitle>
                      {template.category && (
                        <Badge variant="outline" className="mt-2">
                          {template.category}
                        </Badge>
                      )}
                      <CardDescription className="mt-2 line-clamp-2">
                        {template.description || '无描述'}
                      </CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="space-y-3">
                    <div>
                      <p className="text-sm font-medium mb-1">支持的变量:</p>
                      <div className="flex flex-wrap gap-1">
                        {template.variables.length > 0 ? (
                          template.variables.map((v) => (
                            <Badge key={v} variant="secondary" className="text-xs">
                              {`{${v}}`}
                            </Badge>
                          ))
                        ) : (
                          <span className="text-sm text-muted-foreground">无</span>
                        )}
                      </div>
                    </div>

                    {template.tags.length > 0 && (
                      <div>
                        <p className="text-sm font-medium mb-1">标签:</p>
                        <div className="flex flex-wrap gap-1">
                          {template.tags.map((tag) => (
                            <Badge key={tag} variant="outline" className="text-xs">
                              {tag}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="text-sm text-muted-foreground">
                      使用次数: {template.usage_count}
                    </div>

                    <div className="flex flex-wrap gap-2 pt-2" onClick={(e) => e.stopPropagation()}>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handlePreview(template)}
                      >
                        <Eye className="w-3 h-3 mr-1" />
                        预览
                      </Button>
                      {!template.is_system && (
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleEdit(template)}
                          >
                            <Edit className="w-3 h-3 mr-1" />
                            编辑
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleDelete(template)}
                          >
                            <Trash2 className="w-3 h-3 mr-1" />
                            删除
                          </Button>
                        </>
                      )}
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleDuplicate(template)}
                      >
                        <Copy className="w-3 h-3 mr-1" />
                        复制
                      </Button>
                      <Button
                        size="sm"
                        variant={template.is_active ? 'outline' : 'default'}
                        onClick={() => handleToggleActive(template)}
                      >
                        {template.is_active ? '停用' : '启用'}
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Preview Dialog */}
      <Dialog open={previewDialogOpen} onOpenChange={setPreviewDialogOpen}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {previewTemplate?.name}
              {previewTemplate?.is_system && <Badge variant="secondary">系统</Badge>}
              {previewTemplate?.is_active ? (
                <Badge variant="success">
                  <Check className="w-3 h-3 mr-1" />
                  启用
                </Badge>
              ) : (
                <Badge variant="soft">
                  <X className="w-3 h-3 mr-1" />
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
        <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
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
      </PageScaffold>
    </AppFrame>
  )
}
