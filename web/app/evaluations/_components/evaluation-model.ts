import type { RagasItem, RagasRunDetail } from '@/lib/api/evaluation'
import type { JsonObject } from '@/types'

export const LOW_SCORE_THRESHOLD=0.8
const LABELS: Record<string,string>={faithfulness:'忠实度',response_relevancy:'回答相关性',context_precision:'上下文精准度'}
export function metricName(key: string) { return LABELS[key] || key }
export function numericScore(value: unknown): number | null { return typeof value==='number' && Number.isFinite(value)?value:null }
export function hasLowScore(item: RagasItem, metrics: string[]) { return metrics.some(key=>{const value=numericScore(item.scores?.[key]);return value!==null && value<LOW_SCORE_THRESHOLD}) }
export function metricStatistics(detail: RagasRunDetail | null, metrics: string[]) {
  return metrics.map(key=>{
    const values=(detail?.items||[]).flatMap(item=>{const score=numericScore(item.scores?.[key]);return score===null?[]:[score]}).sort((a,b)=>a-b)
    const percentile=(p:number)=>values.length?values[Math.min(values.length-1,Math.floor((p/100)*(values.length-1)))]:null
    return {key,label:metricName(key),mean:numericScore(detail?.run.summary?.[key]) ?? (values.length?values.reduce((a,b)=>a+b,0)/values.length:null),p50:percentile(50),p90:percentile(90),passRate:values.length?values.filter(value=>value>=LOW_SCORE_THRESHOLD).length/values.length:null}
  })
}
export function itemContexts(item: RagasItem) {
  const contexts=(item.retrieved_contexts||[]).filter(text=>typeof text==='string' && text.trim())
  if(contexts.length) return contexts
  return (item.citations||[]).flatMap(citation=>{
    if(!citation || typeof citation!=='object') return []
    const data=citation as JsonObject
    const value=data.content || data.text || data.quote
    return typeof value==='string' && value.trim()?[value]:[]
  })
}
export function displayDate(value: string | undefined) { if(!value)return '—';const date=new Date(value);return Number.isNaN(date.getTime())?'—':date.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) }
export function runDuration(start?: string,end?: string) { if(!start||!end)return null;const ms=new Date(end).getTime()-new Date(start).getTime();return Number.isFinite(ms)&&ms>=0?`${(ms/1000).toFixed(1)} 秒`:null }
