'use client'

import { useMemo, useState } from 'react'
import dynamic from 'next/dynamic'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { enterpriseOntologyApi } from '@/lib/api/enterprise-ontology'
import { extractHttpStatus, formatApiError } from '@/lib/api-errors'
import type { GraphData } from '@/lib/graph-types'
import type { EnterpriseOntologyDocumentGraph, EnterpriseOntologyGraphChanges } from '@/types/enterprise-ontology'
import type { OntologyGraphItem } from '../graph-page-utils'

const GraphViewer = dynamic(() => import('@/components/graph/graph-viewer').then((module) => module.GraphViewer), {
  ssr: false,
})
const field = 'grid min-w-0 gap-1.5 text-sm'
const select = 'h-11 w-full min-w-0 rounded-md border border-input bg-background px-2 sm:h-9'

type Changes = EnterpriseOntologyGraphChanges
type Entity = Changes['entities'][number]
type Relation = Changes['relations'][number]
type Span = Entity['evidence']
type Selection = { kind: 'entity' | 'relation'; index: number }
type Attribute = { value: string; quote: string; previous?: Span; originalValue?: string | number | boolean }

function sourceSpan(text: string, quote: string, previous?: Span): Span {
  if (previous?.quote === quote && Array.from(text).slice(previous.start_char, previous.end_char).join('') === quote) {
    return previous
  }
  const offset = text.indexOf(quote)
  if (!quote.trim() || offset < 0) throw new Error('请复制文档中的原文作为证据。')
  if (text.indexOf(quote, offset + 1) >= 0) throw new Error('原文有多处相同文本，请补充上下文。')
  const start = Array.from(text.slice(0, offset)).length
  return { quote, start_char: start, end_char: start + Array.from(quote).length, source: 'quote' }
}

export function OntologyChunkEditor({
  datasetId,
  documentName,
  view,
  initialItem,
  onDirtyChange,
  onReload,
  onSaved,
}: {
  datasetId: string
  documentName?: string
  view: EnterpriseOntologyDocumentGraph
  initialItem?: OntologyGraphItem
  onDirtyChange: (dirty: boolean) => void
  onReload: () => Promise<unknown>
  onSaved: (restored: boolean, updated: EnterpriseOntologyDocumentGraph) => void
}) {
  const original = useMemo<Changes>(
    () => ({ entities: view.chunk.entities ?? [], relations: view.chunk.relations ?? [] }),
    [view.chunk],
  )
  const [draft, setDraft] = useState(original)
  const [selection, setSelection] = useState<Selection | null>(() => {
    if (!initialItem) return null
    if ('entityId' in initialItem) {
      const index = original.entities.findIndex((item) => item.id === initialItem.entityId)
      return index >= 0 ? { kind: 'entity', index } : null
    }
    const index = original.relations.findIndex(
      (item) =>
        item.subject_id === initialItem.subjectId &&
        item.object_id === initialItem.objectId &&
        item.predicate === initialItem.predicate &&
        item.evidence.start_char === initialItem.startChar &&
        item.evidence.end_char === initialItem.endChar,
    )
    return index >= 0 ? { kind: 'relation', index } : null
  })
  const [targetMissing] = useState(initialItem !== undefined && selection === null)
  const [tab, setTab] = useState(initialItem && 'predicate' in initialItem ? 'relations' : 'entities')
  const [pending, setPending] = useState(false)
  const [formDirty, setFormDirty] = useState(false)
  const [issue, setIssue] = useState<{ message: string; conflict: boolean } | null>(null)
  const dirty = JSON.stringify(draft) !== JSON.stringify(original)
  const graph = useMemo<GraphData>(
    () => ({
      nodes: draft.entities.map((item) => ({
        id: item.id,
        label: item.name,
        meta: { kind: 'entity', type: item.object_type },
      })),
      links: draft.relations.map((item, index) => ({
        id: String(index),
        source: item.subject_id,
        target: item.object_id,
        label: view.relations[item.predicate]?.label || item.predicate,
        kind: 'entity_relation',
      })),
    }),
    [draft, view.relations],
  )
  const selectedEntity = selection?.kind === 'entity' ? draft.entities[selection.index] : undefined
  const selectedRelation = selection?.kind === 'relation' ? draft.relations[selection.index] : undefined
  const entityName = (id: string) => draft.entities.find((entity) => entity.id === id)?.name ?? id

  function choose(kind: Selection['kind'], index: number) {
    if (pending || formDirty) return
    setSelection({ kind, index })
    setTab(kind === 'entity' ? 'entities' : 'relations')
  }

  function apply(next: Changes) {
    setDraft(next)
    setFormDirty(false)
    setSelection(null)
    setIssue(null)
    onDirtyChange(JSON.stringify(next) !== JSON.stringify(original))
  }

  function editForm() {
    setFormDirty(true)
    onDirtyChange(true)
  }

  function cancelForm() {
    setSelection(null)
    setFormDirty(false)
    onDirtyChange(dirty)
  }

  function applyEntity(entity: Entity) {
    const index = selection?.index ?? -1
    const entities = [...draft.entities]
    if (index < 0) entities.push(entity)
    else entities[index] = entity
    apply({ ...draft, entities })
  }

  function applyRelation(relation: Relation) {
    const index = selection?.index ?? -1
    const relations = [...draft.relations]
    if (index < 0) relations.push(relation)
    else relations[index] = relation
    apply({ ...draft, relations })
  }

  async function save(graphChanges: Changes | null) {
    setIssue(null)
    setPending(true)
    onDirtyChange(true)
    try {
      const updated = await enterpriseOntologyApi.editDocumentGraph(
        datasetId,
        view.chunk.document_id,
        view.chunk.chunk_id,
        {
          version_id: view.version_id,
          expected_revision: view.revision,
          graph: graphChanges,
        },
      )
      onDirtyChange(false)
      onSaved(graphChanges === null, updated)
    } catch (error) {
      setIssue({ message: formatApiError(error, '保存图谱修正失败'), conflict: extractHttpStatus(error) === 409 })
      onDirtyChange(dirty)
    } finally {
      setPending(false)
    }
  }

  return (
    <section aria-label="文档图谱与修正" className="grid min-w-0 gap-3 border-t pt-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        <strong className="break-all">{documentName ?? '当前文档'}</strong>
        <span className="text-muted-foreground">本体版本 {view.version_number}</span>
        {view.corrected && <span className="text-muted-foreground">已人工修正</span>}
        {!view.can_edit && <span className="text-muted-foreground">只读</span>}
      </div>
      {targetMissing && (
        <p role="status" className="text-sm text-muted-foreground">
          所选对象已更新，请在当前分块重新选择。
        </p>
      )}
      <div className="grid min-w-0 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,23rem)]">
        <div className="grid min-w-0 gap-2">
          <div className="relative h-44 overflow-hidden rounded-md border border-border sm:h-64">
            {graph.nodes.length > 0 ? (
              <GraphViewer
                appearance="diagram"
                data={graph}
                selectedNodeId={selectedEntity?.id}
                showEdgeLabels
                showMinimap={false}
                onNodeClick={(node) =>
                  choose(
                    'entity',
                    draft.entities.findIndex((item) => item.id === node.id),
                  )
                }
                onLinkClick={(link) => choose('relation', Number(link.id))}
              />
            ) : (
              <p className="p-4 text-sm text-muted-foreground">这个分块暂无实体。</p>
            )}
          </div>
          <label className={field}>
            分块原文
            <Textarea readOnly rows={4} className="resize-y" value={view.source_text} />
          </label>
        </div>
        <Tabs
          value={tab}
          onValueChange={(value) => {
            setTab(value)
            setSelection(null)
          }}
          className="order-first min-w-0 lg:order-none"
        >
          <TabsList aria-label="本体图谱对象">
            <TabsTrigger value="entities" disabled={pending || formDirty}>
              实体
            </TabsTrigger>
            <TabsTrigger value="relations" disabled={pending || formDirty}>
              关系
            </TabsTrigger>
          </TabsList>
          <TabsContent value="entities" className="grid gap-2">
            <label className={field}>
              选择实体
              <select
                className={select}
                value={selectedEntity?.id ?? ''}
                disabled={pending || formDirty}
                onChange={(event) => {
                  const index = draft.entities.findIndex((item) => item.id === event.target.value)
                  if (index < 0) setSelection(null)
                  else choose('entity', index)
                }}
              >
                <option value="">选择画布节点或实体</option>
                {draft.entities.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {view.object_types[item.object_type]?.label || item.object_type}
                  </option>
                ))}
              </select>
            </label>
            {selection?.kind === 'entity' ? (
              <EntityForm
                key={selectedEntity?.id ?? 'new-entity'}
                entity={selectedEntity}
                view={view}
                disabled={pending || !view.can_edit}
                onEdit={editForm}
                onCancel={cancelForm}
                onApply={applyEntity}
                onRemove={
                  selectedEntity
                    ? () =>
                        apply({
                          entities: draft.entities.filter((item) => item.id !== selectedEntity.id),
                          relations: draft.relations.filter(
                            (item) => item.subject_id !== selectedEntity.id && item.object_id !== selectedEntity.id,
                          ),
                        })
                    : undefined
                }
              />
            ) : (
              view.can_edit && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="justify-self-start"
                  disabled={pending}
                  onClick={() => choose('entity', -1)}
                >
                  新增实体
                </Button>
              )
            )}
          </TabsContent>
          <TabsContent value="relations" className="grid gap-2">
            <label className={field}>
              选择关系
              <select
                className={select}
                value={selectedRelation && selection ? String(selection.index) : ''}
                disabled={pending || formDirty}
                onChange={(event) =>
                  event.target.value === '' ? setSelection(null) : choose('relation', Number(event.target.value))
                }
              >
                <option value="">选择画布连线或关系</option>
                {draft.relations.map((item, index) => (
                  <option key={index} value={index}>
                    {entityName(item.subject_id)} · {view.relations[item.predicate]?.label || item.predicate} ·{' '}
                    {entityName(item.object_id)}
                  </option>
                ))}
              </select>
            </label>
            {selection?.kind === 'relation' ? (
              <RelationForm
                key={selection.index}
                relation={selectedRelation}
                entities={draft.entities}
                view={view}
                disabled={pending || !view.can_edit}
                onEdit={editForm}
                onCancel={cancelForm}
                onApply={applyRelation}
                onRemove={
                  selectedRelation
                    ? () =>
                        apply({
                          ...draft,
                          relations: draft.relations.filter((_, index) => index !== selection.index),
                        })
                    : undefined
                }
              />
            ) : (
              view.can_edit && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="justify-self-start"
                  disabled={pending || draft.entities.length === 0 || Object.keys(view.relations).length === 0}
                  onClick={() => choose('relation', -1)}
                >
                  新增关系
                </Button>
              )
            )}
          </TabsContent>
        </Tabs>
      </div>
      {issue && (
        <p role="alert" className="break-words text-sm text-destructive">
          {issue.message}
        </p>
      )}
      {view.can_edit && (
        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
          <Button type="button" disabled={pending || formDirty || !dirty} onClick={() => void save(draft)}>
            {pending ? '正在保存…' : '保存图谱修正'}
          </Button>
          {dirty && (
            <Button type="button" variant="ghost" disabled={pending || formDirty} onClick={() => apply(original)}>
              放弃本次修改
            </Button>
          )}
          {view.corrected && !dirty && !formDirty && (
            <Button type="button" variant="outline" disabled={pending} onClick={() => void save(null)}>
              恢复模型抽取
            </Button>
          )}
          {issue?.conflict && (
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={async () => {
                setPending(true)
                try {
                  await onReload()
                  apply(original)
                } catch (error) {
                  setIssue({ message: formatApiError(error, '重新加载本体图谱失败'), conflict: true })
                } finally {
                  setPending(false)
                }
              }}
            >
              放弃本次修改并重新加载
            </Button>
          )}
        </div>
      )}
    </section>
  )
}

function EntityForm({
  entity,
  view,
  disabled,
  onApply,
  onRemove,
  onEdit,
  onCancel,
}: {
  entity?: Entity
  view: EnterpriseOntologyDocumentGraph
  disabled: boolean
  onApply: (entity: Entity) => void
  onRemove?: () => void
  onEdit: () => void
  onCancel: () => void
}) {
  const [type, setType] = useState(entity?.object_type ?? Object.keys(view.object_types)[0] ?? '')
  const [name, setName] = useState(entity?.name ?? '')
  const [quote, setQuote] = useState(entity?.evidence.quote ?? '')
  const [attributes, setAttributes] = useState<Record<string, Attribute[]>>(() =>
    Object.fromEntries(
      Object.entries(entity?.attributes ?? {}).map(([key, values]) => [
        key,
        values.map((item) => ({
          value: String(item.value),
          quote: item.evidence.quote,
          previous: item.evidence,
          originalValue: item.value,
        })),
      ]),
    ),
  )
  const [error, setError] = useState('')
  const objectType = view.object_types[type]

  function submit() {
    try {
      const evidence = sourceSpan(view.source_text, quote, entity?.evidence)
      const populated = Object.fromEntries(
        Object.entries(objectType.properties).flatMap(([key, property]) => {
          const values = (attributes[key] ?? []).filter((item) => item.value.trim())
          return values.length
            ? [
                [
                  key,
                  values.map((item) => ({
                    value:
                      item.originalValue !== undefined && item.value === String(item.originalValue)
                        ? item.originalValue
                        : item.value.trim(),
                    value_type: property.type,
                    evidence: sourceSpan(view.source_text, item.quote || quote, item.previous),
                  })),
                ],
              ]
            : []
        }),
      )
      onApply({
        id: entity?.id ?? globalThis.crypto.randomUUID(),
        name: name.trim(),
        object_type: type,
        evidence,
        attributes: populated,
      })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '请检查实体证据。')
    }
  }

  return (
    <fieldset disabled={disabled} onChange={onEdit} className="grid min-w-0 gap-2">
      <label className={field}>
        实体名称
        <Input value={name} maxLength={255} onChange={(event) => setName(event.target.value)} />
      </label>
      <label className={field}>
        对象类型
        <select className={select} value={type} onChange={(event) => setType(event.target.value)}>
          {Object.entries(view.object_types).map(([id, item]) => (
            <option key={id} value={id}>
              {item.label || id}
            </option>
          ))}
        </select>
      </label>
      <label className={field}>
        实体证据
        <Textarea rows={2} value={quote} onChange={(event) => setQuote(event.target.value)} />
      </label>
      <details className="text-sm">
        <summary className="cursor-pointer">属性和业务主键</summary>
        {Object.entries(objectType?.properties ?? {}).map(([key, property]) => {
          const values = attributes[key] ?? []
          const label = property.label || key
          return (
            <div key={key} className="mt-2 grid gap-1.5 border-t pt-2">
              <strong className="break-words font-medium">
                {label}
                {objectType.key.includes(key) ? ' · 主键' : ''}
              </strong>
              {values.map((item, index) => {
                const setValue = (next: Attribute) =>
                  setAttributes({
                    ...attributes,
                    [key]: values.map((existing, position) => (position === index ? next : existing)),
                  })
                return (
                  <div key={index} className="grid gap-1.5">
                    <label className={field}>
                      {label}的值
                      <Input
                        value={item.value}
                        onChange={(event) => setValue({ ...item, value: event.target.value })}
                      />
                    </label>
                    <label className={field}>
                      {label}的原文
                      <Input
                        value={item.quote}
                        onChange={(event) => setValue({ ...item, quote: event.target.value })}
                      />
                    </label>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="justify-self-start"
                      onClick={() => {
                        onEdit()
                        setAttributes({ ...attributes, [key]: values.filter((_, position) => position !== index) })
                      }}
                    >
                      移除该值
                    </Button>
                  </div>
                )
              })}
              {(values.length === 0 || property.multiple) && !disabled && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="justify-self-start"
                  onClick={() => {
                    onEdit()
                    setAttributes({ ...attributes, [key]: [...values, { value: '', quote: '' }] })
                  }}
                >
                  填写{label}
                </Button>
              )}
            </div>
          )
        })}
      </details>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {!disabled && (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!name.trim() || !type || !quote.trim()}
            onClick={submit}
          >
            应用实体修改
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
            取消编辑
          </Button>
          {onRemove && (
            <Button type="button" size="sm" variant="ghost" className="text-destructive" onClick={onRemove}>
              移除实体及连线
            </Button>
          )}
        </div>
      )}
    </fieldset>
  )
}

function RelationForm({
  relation,
  entities,
  view,
  disabled,
  onApply,
  onRemove,
  onEdit,
  onCancel,
}: {
  relation?: Relation
  entities: Entity[]
  view: EnterpriseOntologyDocumentGraph
  disabled: boolean
  onApply: (relation: Relation) => void
  onRemove?: () => void
  onEdit: () => void
  onCancel: () => void
}) {
  const [predicate, setPredicate] = useState(relation?.predicate ?? Object.keys(view.relations)[0] ?? '')
  const [subject, setSubject] = useState(relation?.subject_id ?? '')
  const [object, setObject] = useState(relation?.object_id ?? '')
  const [quote, setQuote] = useState(relation?.evidence.quote ?? '')
  const [error, setError] = useState('')
  const definition = view.relations[predicate]
  const starts = entities.filter((item) => item.object_type === definition?.from)
  const ends = entities.filter((item) => item.object_type === definition?.to)

  function submit() {
    try {
      const evidence = sourceSpan(view.source_text, quote, relation?.evidence)
      onApply({ subject_id: subject, object_id: object, predicate, evidence })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '请检查关系证据。')
    }
  }

  return (
    <fieldset disabled={disabled} onChange={onEdit} className="grid min-w-0 gap-2">
      <label className={field}>
        关系类型
        <select
          className={select}
          value={predicate}
          onChange={(event) => {
            setPredicate(event.target.value)
            setSubject('')
            setObject('')
          }}
        >
          {Object.entries(view.relations).map(([id, item]) => (
            <option key={id} value={id}>
              {item.label || id}
            </option>
          ))}
        </select>
      </label>
      <label className={field}>
        起点实体
        <select className={select} value={subject} onChange={(event) => setSubject(event.target.value)}>
          <option value="">选择起点</option>
          {starts.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      <label className={field}>
        终点实体
        <select className={select} value={object} onChange={(event) => setObject(event.target.value)}>
          <option value="">选择终点</option>
          {ends.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      <label className={field}>
        关系证据
        <Textarea rows={2} value={quote} onChange={(event) => setQuote(event.target.value)} />
      </label>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {!disabled && (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={
              !starts.some((item) => item.id === subject) || !ends.some((item) => item.id === object) || !quote.trim()
            }
            onClick={submit}
          >
            应用关系修改
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
            取消编辑
          </Button>
          {onRemove && (
            <Button type="button" size="sm" variant="ghost" className="text-destructive" onClick={onRemove}>
              移除关系
            </Button>
          )}
        </div>
      )}
    </fieldset>
  )
}
