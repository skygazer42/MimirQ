import type { IngestionPolicy, IngestionRule } from '@/types'

export type RuleDraft = {
  id: string; name: string; enabled: boolean; extensionsText: string; filenameRegex: string
  preprocessEnabled: boolean; preprocessStepIds: string[]; stepParams: Record<string, Record<string, unknown>>
  parserBackend: string; chunkStrategy: string; governanceProfileRef: string; pipelinePatchJson: string
}
export type TemplatePlacement = 'prepend' | 'append' | 'replace'

export function newRuleDraft(id: string): RuleDraft {
  return { id, name: '', enabled: true, extensionsText: '.pdf', filenameRegex: '', preprocessEnabled: true, preprocessStepIds: ['text.reencode_utf8', 'text.strip_bom', 'text.normalize_newlines'], stepParams: {}, parserBackend: 'auto', chunkStrategy: '', governanceProfileRef: '', pipelinePatchJson: '' }
}
export function ruleToDraft(rule: IngestionRule): RuleDraft {
  const steps = rule.preprocess?.steps ?? []
  return {
    id: rule.id, name: rule.name, enabled: rule.enabled, extensionsText: (rule.match?.extensions ?? []).join(', '), filenameRegex: rule.match?.filename_regex ?? '',
    preprocessEnabled: rule.preprocess?.enabled ?? true, preprocessStepIds: steps.map(step => step.id), stepParams: Object.fromEntries(steps.map(step => [step.id, step.params ?? {}])),
    parserBackend: rule.parser_backend ?? '', chunkStrategy: rule.chunk_strategy ?? '', governanceProfileRef: rule.governance_profile_ref ?? '',
    pipelinePatchJson: Object.keys(rule.pipeline_patch ?? {}).length ? JSON.stringify(rule.pipeline_patch, null, 2) : '',
  }
}
export function draftToRule(draft: RuleDraft, rules: IngestionRule[], originalId: string | null): IngestionRule {
  const id = draft.id.trim(), name = draft.name.trim()
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_.:\-]{0,99}$/.test(id)) throw new Error('规则 ID 需以字母或数字开头，最多100个字符，可使用 . _ : -。')
  if (rules.some(rule => rule.id === id && rule.id !== originalId)) throw new Error('规则 ID 已存在，请换一个。')
  if (!name || name.length > 200) throw new Error('请填写规则名称，最多200个字符。')
  const extensions = [...new Set(draft.extensionsText.split(/[,，\s]+/).map(value => value.toLowerCase()).filter(Boolean).map(value => value.startsWith('.') ? value : `.${value}`))]
  if (extensions.length > 30 || extensions.some(value => value.length > 12 || !/^\.[a-z0-9][a-z0-9._-]*$/.test(value))) throw new Error('扩展名格式有误；最多30项，每项不超过12个字符。')
  if (draft.filenameRegex.trim().length > 200) throw new Error('文件名匹配表达式最多200个字符。')
  let patch: Record<string, unknown> = {}
  if (draft.pipelinePatchJson.trim()) {
    const parsed: unknown = JSON.parse(draft.pipelinePatchJson)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('参数覆盖需填写 JSON 对象。')
    patch = parsed as Record<string, unknown>
  }
  return {
    id, name, enabled: draft.enabled, match: { extensions, filename_regex: draft.filenameRegex.trim() || null },
    preprocess: { enabled: draft.preprocessEnabled, steps: draft.preprocessStepIds.map(stepId => ({ id: stepId, params: draft.stepParams[stepId] ?? {} })) },
    parser_backend: draft.parserBackend || null, chunk_strategy: draft.chunkStrategy || null, governance_profile_ref: draft.governanceProfileRef || null, pipeline_patch: patch,
  }
}
export function insertTemplate(rules: IngestionRule[], additions: IngestionRule[], placement: TemplatePlacement) {
  const next = placement === 'replace' ? additions : placement === 'append' ? [...rules, ...additions] : [...additions, ...rules]
  if (next.length > 60) throw new Error('一套策略最多60条规则，请减少后再添加。')
  return next
}
export function policyPayload(policy: IngestionPolicy): IngestionPolicy { return { version: policy.version ?? '1', rules: policy.rules ?? [] } }
export function formatPolicyDate(value: string | null | undefined) {
  if (!value) return '未记录'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date).replaceAll('/', '-')
}
