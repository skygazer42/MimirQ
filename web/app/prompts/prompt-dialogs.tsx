'use client'

import dynamic from 'next/dynamic'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Copy, Loader2 } from '@/components/icons'
import { promptDate, promptScenario } from './prompt-model'
import { PromptStatus, PromptVariables } from './prompt-table'
import type { PromptsController } from './use-prompt-templates'
import styles from './prompts.module.css'

const KgExtractPromptSettings = dynamic(
  () => import('@/components/kg-extract-prompt-settings').then((m) => m.KgExtractPromptSettings),
  { loading: () => <p className={styles.dialogLoading}>加载场景配置…</p> },
)
const KgPredicateOntologySettings = dynamic(
  () => import('@/components/kg-predicate-ontology-settings').then((m) => m.KgPredicateOntologySettings),
  { loading: () => <p className={styles.dialogLoading}>加载关系词表…</p> },
)

export function PromptDialogs({ controller }: { controller: PromptsController }) {
  const previewTemplate = controller.preview
  return (
    <>
      <Dialog
        open={controller.editorOpen}
        onOpenChange={(open) => {
          if (controller.busy !== 'save') controller.setEditorOpen(open)
        }}
      >
        <DialogContent className={styles.editorDialog} onCloseAutoFocus={controller.restoreFocus}>
          <form
            className={styles.dialogForm}
            onSubmit={(event) => {
              event.preventDefault()
              void controller.save()
            }}
          >
            <DialogHeader className={styles.dialogHeader}>
              <DialogTitle>{controller.editingTemplate ? '编辑模板' : '创建模板'}</DialogTitle>
              <DialogDescription>用 {'{变量名}'} 标记需要传入的内容。</DialogDescription>
            </DialogHeader>
            <div className={styles.dialogBody}>
              <fieldset disabled={Boolean(controller.busy)} className={styles.formFields}>
                <div className={styles.field}>
                  <Label htmlFor="prompt-name">模板名称</Label>
                  <Input
                    id="prompt-name"
                    required
                    maxLength={200}
                    autoComplete="off"
                    value={controller.draft.name}
                    onChange={(event) => controller.setDraft({ ...controller.draft, name: event.target.value })}
                    placeholder="例如：技术文档问答"
                  />
                </div>
                <div className={styles.field}>
                  <Label htmlFor="prompt-description">
                    用途说明 <span>选填</span>
                  </Label>
                  <Input
                    id="prompt-description"
                    value={controller.draft.description}
                    onChange={(event) => controller.setDraft({ ...controller.draft, description: event.target.value })}
                    placeholder="这个模板用于回答什么问题"
                  />
                </div>
                <div className={styles.field}>
                  <Label htmlFor="prompt-content">模板正文</Label>
                  <Textarea
                    id="prompt-content"
                    className={styles.contentInput}
                    required
                    value={controller.draft.content}
                    onChange={(event) => controller.setDraft({ ...controller.draft, content: event.target.value })}
                    placeholder={'请根据 {context} 回答问题：{question}'}
                    spellCheck={false}
                  />
                </div>
                <div className={styles.twoFields}>
                  <div className={styles.field}>
                    <Label htmlFor="prompt-variables">
                      变量 <span>逗号分隔</span>
                    </Label>
                    <Input
                      id="prompt-variables"
                      value={controller.draft.variablesText}
                      onChange={(event) =>
                        controller.setDraft({ ...controller.draft, variablesText: event.target.value })
                      }
                      placeholder="context, question, history"
                      spellCheck={false}
                    />
                  </div>
                  <div className={styles.field}>
                    <Label htmlFor="prompt-category">
                      分类 <span>选填</span>
                    </Label>
                    <Input
                      id="prompt-category"
                      maxLength={100}
                      value={controller.draft.category}
                      onChange={(event) => controller.setDraft({ ...controller.draft, category: event.target.value })}
                      placeholder="例如：rag_answer"
                      list="prompt-categories"
                    />
                    <datalist id="prompt-categories">
                      {controller.categories.map((category) => (
                        <option key={category} value={category} />
                      ))}
                    </datalist>
                  </div>
                </div>
                <div className={styles.field}>
                  <Label htmlFor="prompt-tags">
                    标签 <span>选填，逗号分隔</span>
                  </Label>
                  <Input
                    id="prompt-tags"
                    value={controller.draft.tagsText}
                    onChange={(event) => controller.setDraft({ ...controller.draft, tagsText: event.target.value })}
                    placeholder="技术, 引用, 中文"
                  />
                </div>
                <div className={styles.enableField}>
                  <Label htmlFor="prompt-active">启用模板</Label>
                  <Switch
                    id="prompt-active"
                    checked={controller.draft.is_active}
                    onCheckedChange={(value) => controller.setDraft({ ...controller.draft, is_active: value })}
                  />
                </div>
              </fieldset>
              {controller.formError ? (
                <p className={styles.formError} role="alert">
                  {controller.formError}
                </p>
              ) : null}
            </div>
            <DialogFooter className={styles.dialogFooter}>
              <Button
                type="button"
                variant="outline"
                disabled={controller.busy === 'save'}
                onClick={() => controller.setEditorOpen(false)}
              >
                取消
              </Button>
              <Button
                type="submit"
                className={styles.primary}
                disabled={Boolean(controller.busy) || !controller.draft.name.trim() || !controller.draft.content.trim()}
              >
                {controller.busy === 'save' ? <Loader2 className="animate-spin" /> : null}
                {controller.busy === 'save' ? '保存中' : '保存模板'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog
        open={previewTemplate !== null}
        onOpenChange={(open) => {
          if (!open) controller.setPreview(null)
        }}
      >
        <DialogContent
          className={styles.previewDialog}
          onCloseAutoFocus={(event) => {
            if (controller.editorOpen) event.preventDefault()
            else controller.restoreFocus(event)
          }}
        >
          {previewTemplate ? (
            <>
              <DialogHeader className={styles.dialogHeader}>
                <DialogTitle title={previewTemplate.name}>{previewTemplate.name}</DialogTitle>
                <DialogDescription className="sr-only">模板用途、变量及正文</DialogDescription>
              </DialogHeader>
              <div className={styles.dialogBody}>
                {previewTemplate.name.length > 70 ? (
                  <p className={styles.previewDescription}>{previewTemplate.name}</p>
                ) : null}
                {previewTemplate.description ? (
                  <p className={styles.previewDescription}>{previewTemplate.description}</p>
                ) : null}
                <dl className={styles.previewFacts}>
                  <div>
                    <dt>场景 / 分类</dt>
                    <dd>
                      {promptScenario(previewTemplate.category).label}
                      <small>{previewTemplate.category ?? '未分类'}</small>
                    </dd>
                  </div>
                  <div>
                    <dt>来源</dt>
                    <dd>{previewTemplate.is_system ? '内置 · 只读' : '自定义'}</dd>
                  </div>
                  <div>
                    <dt>状态</dt>
                    <dd>
                      <PromptStatus template={previewTemplate} />
                    </dd>
                  </div>
                  <div>
                    <dt>使用次数</dt>
                    <dd>{previewTemplate.usage_count.toLocaleString()}</dd>
                  </div>
                </dl>
                <div className={styles.previewVariables}>
                  <h3>
                    模板变量 <small>{previewTemplate.variables.length} 个</small>
                  </h3>
                  <PromptVariables variables={previewTemplate.variables} />
                </div>
                {previewTemplate.tags.length ? (
                  <div className={styles.previewTags}>
                    <h3>标签</h3>
                    <p>{previewTemplate.tags.join(' · ')}</p>
                  </div>
                ) : null}
                <div className={styles.contentHeading}>
                  <h3>模板正文</h3>
                  <span>
                    v{previewTemplate.version} · {promptDate(previewTemplate.updated_at, true)} 更新
                  </span>
                </div>
                <pre className={styles.previewContent}>{previewTemplate.content}</pre>
              </div>
              <DialogFooter className={styles.dialogFooter}>
                <Button variant="outline" onClick={() => controller.setPreview(null)}>
                  关闭
                </Button>
                {controller.canManage && !previewTemplate.is_system ? (
                  <Button
                    variant="outline"
                    disabled={Boolean(controller.busy)}
                    onClick={() => controller.openEditor(previewTemplate)}
                  >
                    编辑模板
                  </Button>
                ) : null}
                {controller.canManage ? (
                  <Button
                    className={styles.primary}
                    disabled={Boolean(controller.busy)}
                    onClick={() => {
                      void controller.duplicate(previewTemplate)
                    }}
                  >
                    {controller.busy === `copy:${previewTemplate.id}` ? <Loader2 className="animate-spin" /> : <Copy />}
                    复制为自定义模板
                  </Button>
                ) : null}
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
      <AlertDialog
        open={controller.deleteTargets.length > 0}
        onOpenChange={(open) => {
          if (!open && !controller.busy) controller.closeDelete()
        }}
      >
        <AlertDialogContent className={styles.deleteDialog} onCloseAutoFocus={controller.restoreFocus}>
          <AlertDialogHeader>
            <AlertDialogTitle>
              删除{controller.deleteTargets.length > 1 ? ` ${controller.deleteTargets.length} 个` : ''}模板？
            </AlertDialogTitle>
            <AlertDialogDescription>
              {controller.deleteTargets.length === 1
                ? `将删除「${controller.deleteTargets[0].name}」。`
                : `将删除所选的 ${controller.deleteTargets.length} 个自定义模板。`}
              此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          {controller.actionError ? (
            <p className={styles.formError} role="alert">
              {controller.actionError}
            </p>
          ) : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={Boolean(controller.busy)}>取消</AlertDialogCancel>
            <Button
              variant="destructive"
              disabled={Boolean(controller.busy)}
              onClick={() => {
                void controller.confirmDelete()
              }}
            >
              {controller.busy === 'delete' ? <Loader2 className="animate-spin" /> : null}
              {controller.busy === 'delete'
                ? '删除中'
                : `删除${controller.deleteTargets.length > 1 ? ` ${controller.deleteTargets.length} 个模板` : '模板'}`}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <Dialog open={controller.bindingOpen} onOpenChange={controller.setBindingOpen}>
        <DialogContent className={styles.bindingDialog} onCloseAutoFocus={controller.restoreFocus}>
          <DialogHeader className={styles.dialogHeader}>
            <DialogTitle>场景绑定</DialogTitle>
            <DialogDescription>选择各场景使用的模板，维护知识图谱关系词表。</DialogDescription>
          </DialogHeader>
          {controller.bindingOpen ? (
            <Tabs defaultValue="templates" className={styles.bindingTabs}>
              <TabsList className={styles.bindingTabList} aria-label="绑定配置类型">
                <TabsTrigger value="templates">场景模板</TabsTrigger>
                <TabsTrigger value="predicates">关系词表</TabsTrigger>
              </TabsList>
              <TabsContent value="templates" className={styles.bindingBody}>
                <KgExtractPromptSettings templates={controller.templates} />
              </TabsContent>
              <TabsContent value="predicates" className={styles.bindingBody}>
                <KgPredicateOntologySettings />
              </TabsContent>
            </Tabs>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  )
}
