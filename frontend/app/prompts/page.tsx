'use client'

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { promptTemplateApi, PromptTemplate, PromptTemplateCreate } from '@/lib/api-client'
import { Plus, Edit, Trash2, Copy, Check, X } from 'lucide-react'
import { toast } from 'sonner'

export default function PromptsPage() {
  const [templates, setTemplates] = useState<PromptTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingTemplate, setEditingTemplate] = useState<PromptTemplate | null>(null)

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
    <div className="container mx-auto py-8">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold">提示词模板管理</h1>
          <p className="text-muted-foreground mt-2">
            创建和管理您的 RAG 对话提示词模板
          </p>
        </div>
        <Button onClick={handleCreate}>
          <Plus className="w-4 h-4 mr-2" />
          创建模板
        </Button>
      </div>

      {loading ? (
        <div className="text-center py-12">加载中...</div>
      ) : templates.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <p>还没有提示词模板</p>
            <Button onClick={handleCreate} className="mt-4">
              创建第一个模板
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {templates.map((template) => (
            <Card key={template.id} className="relative">
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <CardTitle className="flex items-center gap-2">
                      {template.name}
                      {template.is_system && (
                        <Badge variant="secondary">系统</Badge>
                      )}
                      {template.is_active ? (
                        <Badge variant="default" className="bg-green-600">
                          <Check className="w-3 h-3 mr-1" />
                          启用
                        </Badge>
                      ) : (
                        <Badge variant="secondary">
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
                  </div>
                </div>
                <CardDescription className="mt-2">
                  {template.description || '无描述'}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div>
                    <p className="text-sm font-medium mb-2">支持的变量:</p>
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

                  <div>
                    <p className="text-sm text-muted-foreground">
                      使用次数: {template.usage_count}
                    </p>
                  </div>

                  <div className="flex gap-2 pt-2">
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
      )}

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
    </div>
  )
}
