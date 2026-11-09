import type { PromptPreviewResponse } from '@/types'
import { buildRagPreviewDiagnosticsSummary } from '@/lib/rag-preview-diagnostics'

export type JsonRecord=Record<string,unknown>
export type Tone='neutral'|'success'|'warning'|'danger'|'info'
export type Verdict={label:string;tone:Tone}
export type Metric={key:string;label:string;value:string;unit:string;source:string;raw:number|null}
export function record(value:unknown):JsonRecord {return value!==null&&typeof value==='object'&&!Array.isArray(value)?value as JsonRecord:{}}
export function text(value:unknown):string|null {return typeof value==='string'&&value.trim()?value.trim():null}
export function readNumber(value:unknown):number|null {
  if(typeof value!=='number'&&(typeof value!=='string'||!value.trim()))return null
  const n=Number(value);return Number.isFinite(n)?n:null
}
export function firstNumber(source:unknown,keys:string[]) {
  const obj=record(source)
  for(const key of keys){const value=readNumber(obj[key]);if(value!==null)return {value,key}}
  return null
}
export function numeric(value:number|null,digits=3){return value===null?'未返回':value.toLocaleString('zh-CN',{maximumFractionDigits:digits})}
export function timestamp(value?:string|number|null) {
  if(value===null||value===undefined||value==='')return '未返回'
  const d=new Date(value);if(Number.isNaN(d.getTime()))return String(value)
  return new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(d)
}

export function metricRows(preview:PromptPreviewResponse|null):Metric[] {
  const metrics=record(preview?.metrics),pending=preview===null
  const metric=(key:string,label:string,keys:string[],unit='',seconds=false):Metric=>{
    let picked=firstNumber(metrics,keys),value=picked?.value??null,source=picked?`metrics.${picked.key}`:'metrics'
    if(key==='latency'&&value===null){picked=firstNumber(metrics,['elapsed_sec','duration_sec','latency_sec','retrieval_elapsed_sec']);value=picked?picked.value*1000:null;source=picked?`metrics.${picked.key}`:'metrics'}
    if(seconds&&value!==null)value*=1000
    return {key,label,raw:value,value:value===null?(pending?'待执行':'未返回'):numeric(value),unit,source}
  }
  const citations=Array.isArray(preview?.citations)?preview.citations.length:null
  return [
    {key:'citations',label:'召回引用',raw:citations,value:citations===null?(pending?'待执行':'未返回'):String(citations),unit:'条',source:'citations'},
    metric('tokens','提示词 token',['prompt_tokens','total_prompt_tokens','input_tokens','tokens_prompt']),
    metric('contexts','上下文 token',['context_tokens','context_token_count']),
    metric('history','历史 token',['history_tokens','history_token_count']),
    metric('latency','执行耗时',['latency_ms','duration_ms','elapsed_ms','total_ms','retrieval_ms'],'ms'),
    metric('relevance','检索相关性',['retrieval_score','retrieval_relevance','retrieval_relevance_score','relevance','similarity_score','similarity']),
    metric('context','上下文相关性',['context_relevance','context_relevancy','context_score','context_precision','context_precision_score']),
    metric('generation','生成质量',['generation_quality','answer_quality','response_relevancy','response_relevance']),
    metric('faithfulness','事实一致性',['faithfulness','faithfulness_score','factual_consistency','fact_consistency']),
    metric('safety','安全评分',['safety_score','safety','policy_compliance','compliance_score']),
  ]
}
export type Channel={key:string;label:string;count:number|null;kind:'vector'|'keyword'|'graph'|'other';evidence:unknown}
function channelEnvelope(explain:unknown) {
  const p=record(explain),direct=record(p.channels)
  return Object.keys(direct).length?direct:record(record(p.query_debug).channels)
}
export function buildChannels(explain:unknown):Channel[] {
  const channels=channelEnvelope(explain),counts=record(channels.counts)
  const nested=Object.entries(counts).filter(([key])=>/_candidates$/.test(key)&&!/^total_/.test(key))
  const ignored=new Set(['timing','counts','retrieval_degraded','retrieval_degraded_reasons','fallback','fallback_reason','degraded','degraded_reason'])
  const entries=nested.length?nested:Object.entries(channels).filter(([key,value])=>!ignored.has(key)&&(readNumber(value)!==null||['candidate_count','candidates','returned_count','hits'].some(field=>Object.hasOwn(record(value),field))))
  return entries.map(([key,value])=>{
    const kind=/vector|dense|semantic|colbert|colpali/i.test(key)?'vector':/keyword|lexical|sparse|bm25|fulltext/i.test(key)?'keyword':/graph|^kg(?:_|$)/i.test(key)?'graph':'other'
    const slug=key.replace(/_candidates$/,'')
    const names:Record<string,string>={vector:'向量召回',dense:'向量召回',keyword:'关键词召回',bm25:'关键词召回',lexical:'词法召回',sparse:'稀疏召回',graph:'图谱召回',kg:'图谱召回',colbert:'ColBERT 召回',colpali:'ColPali 召回'}
    const count=firstNumber(value,['candidate_count','candidates','returned_count','hits'])?.value??readNumber(value)
    return {key,label:names[slug]??slug,kind,count:count!==null&&count>=0?count:null,evidence:{field:nested.length?`channels.counts.${key}`:`channels.${key}`,value}}
  })
}
export function rerankState(explain:unknown,config:unknown):Verdict {
  const used=record(record(explain).rerank).used,enabled=record(config).enable_reranker
  if(used===true)return {label:'已执行',tone:'success'}
  if(used===false)return {label:enabled===false?'未启用':'未执行',tone:'neutral'}
  if(enabled===false)return {label:'未启用',tone:'neutral'}
  if(enabled===true)return {label:'已启用',tone:'info'}
  return {label:'未返回',tone:'neutral'}
}
export function dependencyState(primary:unknown,secondary?:unknown):Verdict {
  const p=record(primary),obj=Object.keys(p).length?p:record(secondary),status=String(obj.status??obj.state??'').toLowerCase()
  if(obj.backend==='memory'&&obj.ok!==false&&!['error','failed','unhealthy','unavailable','disconnected'].includes(status))return {label:'内存模式',tone:'neutral'}
  if(obj.enabled===false||['disabled','skipped','not_configured','not-enabled'].includes(status))return {label:'未启用',tone:'neutral'}
  if(obj.ok===false||['error','failed','disconnected','unhealthy','unavailable'].includes(status))return {label:'异常',tone:'danger'}
  if(obj.ok===true||['ready','connected','ok','healthy','online','enabled','success'].includes(status))return {label:'已连接',tone:'success'}
  if(status==='degraded')return {label:'降级',tone:'warning'}
  return {label:'未知',tone:'neutral'}
}
export function driftVerdict(payload:unknown):Verdict&{ratio:number|null;samples:number|null;above:number|null;average:number|null;error:string|null} {
  const p=record(payload),stats=record(p.drift),above=record(p.above_threshold)
  const ratio=readNumber(above.ratio),samples=readNumber(stats.count)??readNumber(stats.n),count=readNumber(above.count),average=readNumber(stats.avg)??readNumber(stats.mean),error=text(p.error)
  const base={ratio,samples,above:count,average,error}
  if(!Object.keys(p).length)return {...base,label:'待执行',tone:'neutral'}
  if(p.ok===false)return {...base,label:error==='unsupported_vector_backend'?'后端不支持':'检查失败',tone:error==='unsupported_vector_backend'?'neutral':'danger'}
  if(samples===0)return {...base,label:'无可比样本',tone:'neutral'}
  if(samples===null||ratio===null)return {...base,label:'样本信息未返回',tone:'neutral'}
  if(ratio>0||Number(p.dim_mismatch)>0||Number(p.missing_vectors)>0)return {...base,label:'样本需复核',tone:'warning'}
  return {...base,label:'未发现超阈值样本',tone:'success'}
}
export function perfVerdict(payload:unknown):Verdict {
  const p=record(payload)
  if(!Object.keys(p).length)return {label:'待执行',tone:'neutral'}
  const diff=record(p.diff),gate=record(diff.strict_gate),passed=typeof gate.passed==='boolean'?gate.passed:typeof diff.ok==='boolean'?diff.ok:null
  if(passed===true)return {label:'通过',tone:'success'}
  if(passed===false)return {label:'未通过',tone:'warning'}
  return {label:'结论未返回',tone:'neutral'}
}
export function performanceRows(payload:unknown) {
  const p=record(payload),report=record(p.current_report),cases=Array.isArray(report.cases)?report.cases:[],diffCases=record(record(p.diff).cases)
  return cases.map((item,index)=>{
    const c=record(item),latency=record(c.latency_ms),name=text(c.name)??`用例 ${index+1}`,diff=record(diffCases[name])
    return {key:`${name}:${index}`,name,path:text(c.path),iterations:readNumber(c.iterations),okCount:readNumber(c.ok_count),okRatio:readNumber(c.ok_ratio),p50:readNumber(latency.p50),p95:readNumber(latency.p95),p99:readNumber(latency.p99),qps:readNumber(c.qps),regressed:typeof diff.regressed==='boolean'?diff.regressed:null}
  })
}
export type ScopeSnapshot={datasetId:string;datasetName:string;documentIds:string[];documentNames:string[];query:string}
export type PreviewResult={scope:ScopeSnapshot;preview:PromptPreviewResponse;explain:JsonRecord|null;configHash:JsonRecord|null;contractReason:string|null;partialErrors:string[];finishedAt:number}
export function previewSummary(result:PreviewResult|null) {
  const summary=buildRagPreviewDiagnosticsSummary({promptPreview:result?.preview??null,explain:result?.explain??null,configHash:result?.configHash??null,explainEnabled:Boolean(result&&!result.contractReason),contractReason:result?.contractReason??null})
  const truthyFlag=(s:string)=>!/^\w+: false$/.test(s)
  const envelope=channelEnvelope(result?.explain),reasons=Array.isArray(envelope.retrieval_degraded_reasons)?envelope.retrieval_degraded_reasons.filter((v):v is string=>typeof v==='string'&&Boolean(v.trim())):[]
  const timings=[...summary.timings]
  for(const [label,value] of Object.entries(record(envelope.timing))){const n=readNumber(value);if(n!==null&&!timings.some(item=>item.label===label))timings.push({label,value:`${numeric(n,3)}${/_sec$/.test(label)?' s':/_ms$/.test(label)?' ms':''}`})}
  return {...summary,timings,degraded:[...new Set([...summary.degraded.filter(truthyFlag),...(envelope.retrieval_degraded===true?['检索已降级']:[]),...reasons])],fallback:summary.fallback.filter(truthyFlag)}
}
export function validateParams(kind:'drift'|'perf',first:string,second:string):Record<string,string> {
  const a=readNumber(first),b=readNumber(second),errors:Record<string,string>={}
  if(kind==='drift'){
    if(a===null||!Number.isInteger(a)||a<1||a>2000)errors.first='采样数量需为 1–2,000 的整数。'
    if(b===null||b<0||b>1)errors.second='相似度阈值需为 0–1。'
  }else{
    if(a===null||!Number.isInteger(a)||a<1||a>200)errors.first='迭代次数需为 1–200 的整数。'
    if(b===null||b<.05||b>10)errors.second='超时需为 0.05–10 秒。'
  }
  return errors
}
