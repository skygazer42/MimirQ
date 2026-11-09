import type { DatasetReport } from '@/types'
import { formatRetrievalAuditMetric } from './report-format'

export function reportStatusRows(counts: Record<string,number>) {
  const labels: Record<string,string>={completed:'已完成',ready:'已完成',done:'已完成',indexed:'已完成',processing:'处理中',parsing:'解析中',indexing:'索引中',pending:'待处理',queued:'排队中',uploaded:'已上传',failed:'失败',error:'失败',quarantined:'隔离',parsed:'已解析'}
  return Object.entries(counts).filter(([,value])=>Number.isFinite(value)&&value>0).map(([key,value])=>({key,value,label:labels[key]||key,tone:/^(completed|ready|done|indexed)$/.test(key)?'success':/^(failed|error)$/.test(key)?'danger':key==='quarantined'?'warning':'info'}))
}

export function reportAuditRows(audit: DatasetReport['retrieval_audit']) {
  const labels: Record<string,string>={hit_at_1:'召回命中 Hit@1',hit_at_3:'召回命中 Hit@3',expected_metadata_hit_rate:'元数据命中',expected_metadata_recall:'元数据召回',retrieval_effective_context_rate:'有效上下文',retrieval_noise_rate:'噪声占比',kg_noise_rate:'图谱噪声',retrieval_mrr:'MRR',retrieval_ndcg:'NDCG',retrieval_ndcg_at_20:'NDCG@20'}
  return (audit?.gates||[]).flatMap(gate=>Object.entries(labels).flatMap(([key,label])=>Object.prototype.hasOwnProperty.call(gate.metrics||{},key)?[{key:`${gate.name}:${key}`,label,value:/mrr|ndcg/.test(key)&&typeof gate.metrics[key]==='number'&&Number.isFinite(gate.metrics[key])?Number(gate.metrics[key]).toFixed(3):formatRetrievalAuditMetric(gate.metrics[key]),gate:gate.name,status:gate.status}]:[]))
}

export function reportCoverage(value:number,max:number) { return max>0?`${Math.max(0,Math.min(100,value/max*100)).toFixed(1)}%`:'—' }
export function recordedRiskValue(value:number,hasRecord:boolean) { return value>0||hasRecord?String(value):'待评估' }
