import type { Dataset } from '@/types/datasets'

export type DomainTone = 'source' | 'knowledge' | 'process' | 'analysis' | 'governance'

export const DOMAIN_TONES: readonly DomainTone[] = ['source', 'process', 'governance', 'analysis', 'knowledge']

function hashToneIndex(seed: string): number {
  let hash = 0
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) >>> 0
  }
  return hash % DOMAIN_TONES.length
}

export function matchSemanticDomainTone(text: string): DomainTone | null {
  const normalized = text.toLowerCase()
  if (/(评测|测试|golden|eval|图谱|graph|\bkg\b|画像|分析|语料)/i.test(normalized)) return 'analysis'
  if (/(合规|安全|质检|规范|治理|法律|合同|制度|审核|标准|政策|监管)/i.test(normalized)) return 'governance'
  if (/(研发|接口|\bapi\b|架构|解析|parsing|技术|运维|部署|代码|工程|数据库|日志)/i.test(normalized)) return 'process'
  if (/(客服|问答|手册|产品|文档|知识|\bfaq\b|工单|培训|市场|运营|售后)/i.test(normalized)) return 'knowledge'
  if (/(数据|资产|采集|导入|表格|目录|catalog|source)/i.test(normalized)) return 'source'
  return null
}

export function getDatasetDomainTone(dataset: Dataset): DomainTone {
  if (dataset.operational_status === 'testing') return 'analysis'
  const matched = matchSemanticDomainTone(`${dataset.name} ${dataset.description ?? ''}`)
  if (matched) return matched
  if (dataset.pipeline?.kg_enabled) return 'analysis'
  return DOMAIN_TONES[hashToneIndex(dataset.id)]
}

export function getCategoryDomainTone(name: string, index: number, inheritedTone?: DomainTone): DomainTone {
  if (inheritedTone) return inheritedTone
  return matchSemanticDomainTone(name) ?? DOMAIN_TONES[index % DOMAIN_TONES.length]
}

export function getTagDomainTone(tag: string): DomainTone {
  const normalized = tag.trim().toLowerCase()
  const matched = matchSemanticDomainTone(normalized)
  if (matched) return matched
  if (/(验收|审批|归档|风控|保密|敏感)/i.test(normalized)) return 'governance'
  if (/(sop|流程|发布|上线|变更|配置|脚本)/i.test(normalized)) return 'process'
  return DOMAIN_TONES[hashToneIndex(normalized)]
}
