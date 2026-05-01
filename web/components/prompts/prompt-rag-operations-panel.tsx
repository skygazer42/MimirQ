'use client'

import { useState, type ReactNode } from 'react'
import { Image, Loader2, MessageSquare, Settings2 } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { DatasetSelectField } from '@/components/ops/dataset-select-field'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { promptTemplateApi, ragApi, ragConfigTemplateApi, retrievalApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { detachPromise } from '@/lib/utils'

function parseJson(raw: string) {
  const value = raw.trim()
  return value ? JSON.parse(value) : {}
}

export function PromptRagOperationsPanel() {
  const [datasetId, setDatasetId] = useState('')
  const [query, setQuery] = useState('合同风险怎么检索？')
  const [promptTemplateId, setPromptTemplateId] = useState('')
  const [ragTemplateId, setRagTemplateId] = useState('')
  const [ragTemplateJson, setRagTemplateJson] = useState('{\n  "name": "Default retrieval profile",\n  "config_patch": {},\n  "is_active": true\n}')
  const [retrievalJson, setRetrievalJson] = useState('{\n  "query": "合同风险",\n  "top_k": 5\n}')
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null)

  async function runAction(key: string, title: string, action: () => Promise<unknown>) {
    setBusy(key)
    try {
      const payload = await action()
      setResult({ title, payload })
      toast.success(`${title}完成`)
    } catch (error) {
      toast.error(formatApiError(error, `${title}失败`))
    } finally {
      setBusy(null)
    }
  }

  const dataset = datasetId.trim()
  const promptId = promptTemplateId.trim()
  const ragId = ragTemplateId.trim()

  return (
    <section className="rounded-xl border border-slate-200/80 bg-card p-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-sm font-semibold text-foreground">Prompt / RAG 高级操作</div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            围绕选中数据集进行图像检索、retrieval explain/hash 和模板管理；手动模板 ID 与 JSON 编辑默认收起。
          </p>
        </div>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none" /> : null}
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-4">
        <DatasetSelectField value={datasetId} onChange={setDatasetId} />
        <Field label="检索问题">
          <Input value={query} onChange={(event) => setQuery(event.target.value)} className="h-8 text-xs" />
        </Field>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton icon={Image} busy={busy === 'image-index'} disabled={Boolean(busy) || !dataset} label="图像建索引" onClick={() => runAction('image-index', 'CLIP 图像建索引', () => ragApi.indexClipImages({ dataset_id: dataset, top_k: 20, max_chunks: 500, upsert: true }))} />
        <ActionButton icon={Image} busy={busy === 'image-search'} disabled={Boolean(busy) || !dataset || !query.trim()} label="图像检索" onClick={() => runAction('image-search', 'CLIP 图像检索', () => ragApi.searchClipImages({ dataset_id: dataset, query: query.trim(), top_k: 8, auto_index: false }))} />
        <ActionButton icon={MessageSquare} busy={busy === 'prompt-preview'} disabled={Boolean(busy)} label="Prompt Preview" onClick={() => runAction('prompt-preview', 'Prompt Preview', () => ragApi.promptPreview(parseJson(retrievalJson) as any))} />
        <ActionButton icon={Settings2} busy={busy === 'profiles'} disabled={Boolean(busy)} label="Retrieval Profiles" onClick={() => runAction('profiles', 'Retrieval Profiles', () => retrievalApi.listProfiles())} />
        <ActionButton icon={Settings2} busy={busy === 'explain'} disabled={Boolean(busy)} label="Explain" onClick={() => runAction('explain', 'Retrieval Explain', () => retrievalApi.explain(parseJson(retrievalJson)))} />
        <ActionButton icon={Settings2} busy={busy === 'hash'} disabled={Boolean(busy)} label="Config Hash" onClick={() => runAction('hash', 'Retrieval Config Hash', () => retrievalApi.configHash(parseJson(retrievalJson)))} />
        <ActionButton icon={Settings2} busy={busy === 'rag-list'} disabled={Boolean(busy)} label="RAG 模板列表" onClick={() => runAction('rag-list', 'RAG Config Template 列表', () => ragConfigTemplateApi.list({ limit: 50 }))} />
      </div>

      <details className="mt-3 rounded-lg border border-border/60 bg-background/70 p-3">
        <summary className="cursor-pointer text-xs font-semibold text-foreground">高级参数（可选）</summary>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">仅在需要按模板标识读取/版本化，或直接编辑 Prompt/RAG 请求体时使用。</p>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <Field label="Prompt 模板">
            <Input value={promptTemplateId} onChange={(event) => setPromptTemplateId(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
          <Field label="RAG 配置模板">
            <Input value={ragTemplateId} onChange={(event) => setRagTemplateId(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <ActionButton icon={MessageSquare} busy={busy === 'prompt-get'} disabled={Boolean(busy) || !promptId} label="读取 Prompt" onClick={() => runAction('prompt-get', '读取 Prompt 模板', () => promptTemplateApi.get(promptId))} />
          <ActionButton icon={MessageSquare} busy={busy === 'prompt-version'} disabled={Boolean(busy) || !promptId} label="Prompt 新版本" onClick={() => runAction('prompt-version', '创建 Prompt 新版本', () => promptTemplateApi.createVersion(promptId, parseJson(ragTemplateJson)))} />
          <ActionButton icon={Settings2} busy={busy === 'rag-create'} disabled={Boolean(busy)} label="创建 RAG 模板" onClick={() => runAction('rag-create', '创建 RAG Config Template', () => ragConfigTemplateApi.create(parseJson(ragTemplateJson) as any))} />
          <ActionButton icon={Settings2} busy={busy === 'rag-get'} disabled={Boolean(busy) || !ragId} label="读取 RAG 模板" onClick={() => runAction('rag-get', '读取 RAG Config Template', () => ragConfigTemplateApi.get(ragId))} />
          <ActionButton icon={Settings2} busy={busy === 'rag-update'} disabled={Boolean(busy) || !ragId} label="更新 RAG 模板" onClick={() => runAction('rag-update', '更新 RAG Config Template', () => ragConfigTemplateApi.update(ragId, parseJson(ragTemplateJson) as any))} />
          <ActionButton icon={Settings2} busy={busy === 'rag-version'} disabled={Boolean(busy) || !ragId} label="RAG 新版本" onClick={() => runAction('rag-version', '创建 RAG Config Template 新版本', () => ragConfigTemplateApi.createVersion(ragId, parseJson(ragTemplateJson) as any))} />
        </div>

        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <Field label="RAG / Prompt 请求体（JSON）">
            <Textarea value={ragTemplateJson} onChange={(event) => setRagTemplateJson(event.target.value)} className="min-h-[128px] font-mono text-xs" />
          </Field>
          <Field label="Retrieval / Preview 请求体（JSON）">
            <Textarea value={retrievalJson} onChange={(event) => setRetrievalJson(event.target.value)} className="min-h-[128px] font-mono text-xs" />
          </Field>
        </div>
      </details>

      <OperationResultPanel className="mt-3" title="Prompt / RAG 操作结果" result={result} emptyMessage="选择上方操作后，这里展示执行摘要；原始响应默认收起。" />
    </section>
  )
}

function Field({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div className="space-y-1">
      <Label className="text-[11px] font-medium text-muted-foreground">{label}</Label>
      {children}
    </div>
  )
}

function ActionButton({
  busy,
  disabled,
  icon: Icon,
  label,
  onClick,
}: Readonly<{
  busy: boolean
  disabled: boolean
  icon: LucideIcon
  label: string
  onClick: () => Promise<void>
}>) {
  return (
    <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={disabled} onClick={() => detachPromise(onClick())}>
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Icon className="h-3.5 w-3.5" />}
      {label}
    </Button>
  )
}
