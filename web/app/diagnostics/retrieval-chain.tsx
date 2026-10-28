'use client'

import { useRef,useState } from 'react'
import { Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription } from '@/components/ui/dialog'
import { ArrowRight,ArrowRightLeft,Database,Filter,Search,Workflow } from '@/components/icons'
import { buildChannels,record,rerankState,timestamp,type Channel,type Verdict } from './diagnostics-model'
import { Reading,Status } from './diagnostics-controls'
import { CitationOutput } from './citation-output'
import type { DiagnosticsController } from './use-diagnostics'
import { cn } from '@/lib/utils'
import styles from './diagnostics.module.css'

const FIELD_LABELS:Record<string,string>={retrieval_profile:'检索方案',retrieval_mode:'检索模式',score_threshold:'分数阈值',fusion_strategy:'融合策略',alpha:'混合权重 α',enable_reranker:'启用重排',reranker_provider:'重排服务',reranker_top_n:'重排数量',retrieval_contract_mode:'检索约束',visible_evidence_only:'仅使用可见证据',metadata_filter:'元数据过滤',fusion_weights:'融合权重',fusion_budgets:'通道预算',fusion_min_scores:'通道最低分',enable_weight_rerank:'加权重排',vector_weight:'向量权重',keyword_weight:'关键词权重',mmr_lambda:'MMR λ',used:'本次使用',candidates_n:'重排候选',pipeline_stages:'重排阶段',cache_hits:'缓存命中',cache_misses:'缓存未命中'}
const valueLabel=(value:string)=>value==='true'?'是':value==='false'?'否':value==='hybrid'?'混合检索':value
function previewVerdict(c:DiagnosticsController):Verdict {
  if(c.preview.status==='running')return {label:'运行中',tone:'info'}
  if(c.preview.status==='error')return {label:'预览失败',tone:'danger'}
  if(!c.preview.result)return {label:'待执行',tone:'neutral'}
  return c.preview.result.partialErrors.length?{label:'部分信息未取得',tone:'warning'}:{label:'已返回',tone:'success'}
}
export function RetrievalChain({controller:c}:{controller:DiagnosticsController}) {
  const [detail,setDetail]=useState<{label:string;data:unknown;kind?:'citations'}|null>(null)
  const [allChannels,setAllChannels]=useState(false)
  const detailOpener=useRef<HTMLElement|null>(null)
  const openDetail=(next:{label:string;data:unknown;kind?:'citations'},opener:HTMLElement)=>{detailOpener.current=opener;setDetail(next)}
  const r=c.preview.result,summary=c.summary,config=record(r?.configHash?.effective_config)
  const channels=buildChannels(r?.explain).sort((a,b)=>Number(b.count!==null&&b.count>0)-Number(a.count!==null&&a.count>0))
  const nodes:Channel[]=channels.length?(allChannels?channels:channels.slice(0,3)):[{key:'vector',label:'向量召回',kind:'vector',count:null,evidence:null},{key:'keyword',label:'关键词召回',kind:'keyword',count:null,evidence:null}]
  const citations=c.metrics.find(m=>m.key==='citations')!,rerank=rerankState(r?.explain,config)
  const unavailable=r?'未返回':'待执行',filtering=summary.filtering.find(x=>x.label==='score_threshold'),fusion=summary.fusion.find(x=>x.label==='fusion_strategy')
  const params=[...(summary.profile?[{label:'retrieval_profile',value:summary.profile}]:[]),...summary.filtering,...summary.fusion,...summary.reranker]
  const order=['retrieval_mode','fusion_strategy','score_threshold','enable_reranker','retrieval_profile']
  const knownParams=params.filter((item,index)=>params.findIndex(x=>x.label===item.label)===index).sort((a,b)=>(order.includes(a.label)?order.indexOf(a.label):100)-(order.includes(b.label)?order.indexOf(b.label):100))
  const readings=c.metrics.filter(m=>['citations','tokens','contexts','latency'].includes(m.key)&&c.visibleMetrics.includes(m.key))
  const quality=c.metrics.filter(m=>['relevance','context','generation','faithfulness','safety'].includes(m.key)&&c.visibleMetrics.includes(m.key))
  const missingQuality=quality.filter(m=>m.raw===null).length
  const history=c.metrics.find(m=>m.key==='history')!
  const rawRecommendations=record(c.online.data).recommendations
  const recommendations=Array.isArray(rawRecommendations)?rawRecommendations.filter((v):v is string=>typeof v==='string'):[]
  return <>
    <section className={styles.previewResults} aria-label="检索链路" aria-busy={c.preview.status==='running'}>
      <div className={styles.resultsHeading}><h2 tabIndex={-1}>预览结果</h2><Status {...previewVerdict(c)}/><button className={styles.returnToQuery} onClick={()=>document.getElementById('diagnostic-question')?.focus()}>修改查询</button></div>
      {c.preview.error?<div className={styles.domainError} role="alert">{c.preview.error}{r?<span>以下保留 {timestamp(r.finishedAt)} 的上次结果。</span>:null}</div>:null}
      {r?.partialErrors.length?<div className={styles.domainWarning} role="status">{r.partialErrors.map(error=><p key={error}>{error}</p>)}</div>:null}
      {readings.length?<dl className={styles.metricStrip}>{readings.map(metric=><div key={metric.key}><dt>{metric.label}</dt><dd><Reading metric={metric}/></dd></div>)}</dl>:null}
      <section className={styles.chainSection} aria-label="检索过程">
      <div className={styles.sectionHeading}><h3>检索过程</h3><span className={styles.sectionSubtitle}>{r?'基于本次返回字段':'运行预览后查看检索证据'}</span></div>
      <div className={styles.chainScroll}>
        <div className={styles.chainGrid}>
          <div className={styles.channelGroup}><h4>通道候选</h4>{nodes.map(node=><button key={node.key} className={styles.channelReading} disabled={!r||c.preview.status==='running'} data-kind={node.kind} onClick={event=>openDetail({label:node.label,data:node.evidence},event.currentTarget)}><Search/><span>{node.label}</span><strong>{node.count===null?unavailable:node.count}</strong></button>)}{channels.length>3?<button className={styles.quietAction} aria-expanded={allChannels} onClick={()=>setAllChannels(!allChannels)}>{allChannels?'收起通道':`全部通道（${channels.length}）`}</button>:null}</div>
          <ArrowRight className={styles.connector}/>
          <button className={styles.chainNode} disabled={!r||c.preview.status==='running'} onClick={event=>openDetail({label:'过滤配置',data:summary.filtering},event.currentTarget)}><h3><Filter/>过滤配置</h3><p>{filtering?`分数阈值 ≥ ${filtering.value}`:unavailable}</p></button>
          <ArrowRight className={styles.connector}/>
          <button className={styles.chainNode} disabled={!r||c.preview.status==='running'} data-kind="keyword" onClick={event=>openDetail({label:'融合配置',data:summary.fusion},event.currentTarget)}><h3><Workflow/>融合配置</h3><p>{fusion?fusion.value.toUpperCase():unavailable}</p></button>
          <ArrowRight className={styles.connector}/>
          <button className={styles.chainNode} disabled={!r||c.preview.status==='running'} onClick={event=>openDetail({label:'重排状态',data:{configuration:summary.reranker,returned:record(r?.explain).rerank??null}},event.currentTarget)}><h3><ArrowRightLeft/>重排</h3><Status {...(r?rerank:{label:'待执行',tone:'neutral'})}/></button>
          <ArrowRight className={styles.connector}/>
          <button className={cn(styles.chainNode,styles.outputNode)} disabled={!r||c.preview.status==='running'} data-returned={r&&citations.raw!==null||undefined} data-empty={citations.raw===0||undefined} onClick={event=>openDetail({label:'引用输出',data:r?.preview.citations??null,kind:'citations'},event.currentTarget)}><h3><Database/>引用输出</h3><strong><Reading metric={citations}/></strong>{r&&citations.raw===0?<span className={styles.nodeHint}>本次未召回引用</span>:null}</button>
        </div>
      </div>
      {summary.queryForRetrieval?<p className={styles.retrievalQuery}><span>用于检索的问题</span>{summary.queryForRetrieval}</p>:null}
      {r?.contractReason?<p className={styles.contractReason}>{r.contractReason}</p>:null}
      {summary.degraded.length||summary.fallback.length?<div className={styles.domainWarning} role="status"><h3>降级与回退信号</h3>{[...new Set([...summary.degraded,...summary.fallback])].map(message=><p key={message}>{message}</p>)}</div>:null}
      </section>
      <section className={styles.parameterSection} aria-label="检索参数">
        <div className={styles.contractLine}><span>检索方案 <strong>{summary.profile??unavailable}</strong></span><span>配置签名 {summary.configHash?<button className={styles.hashButton} onClick={event=>openDetail({label:'配置签名',data:r?.configHash??null},event.currentTarget)}>{summary.configHash}</button>:<strong>{unavailable}</strong>}</span>{c.visibleMetrics.includes('history')?<span>历史 token <strong><Reading metric={history}/></strong></span>:null}</div>
        {knownParams.length?<details className={styles.parameterDisclosure}><summary>检索参数 <span>{knownParams.length} 项</span></summary><dl className={styles.configRows}>{knownParams.map(item=><div key={item.label}><dt>{FIELD_LABELS[item.label]??item.label}</dt><dd title={item.value}>{valueLabel(item.value)}</dd></div>)}</dl></details>:null}
        {summary.timings.length?<details className={styles.timings}><summary>阶段耗时</summary><dl className={styles.configRows}>{summary.timings.map(item=><div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl></details>:null}
      </section>
      <section className={styles.qualitySection} aria-label="质量读数"><div className={styles.sectionHeading}><h2>评分读数</h2>{r&&missingQuality?<span className={styles.sectionSubtitle}>本次预览未返回 {missingQuality} 项评分</span>:null}</div>{quality.length?<table className={styles.qualityTable} aria-label="诊断评分读数"><thead><tr><th scope="col">指标</th><th scope="col">读数</th><th scope="col">来源字段</th></tr></thead><tbody>{quality.map(metric=><tr key={metric.key}><th scope="row">{metric.label}</th><td><Reading metric={metric}/></td><td>{metric.source}</td></tr>)}</tbody></table>:<p className={styles.sectionEmpty}>未选择评分指标，可在查询栏勾选。</p>}</section>
    </section>
    {recommendations.length?<section className={styles.recommendations}><h2>后端建议</h2>{recommendations.map((v,index)=><p key={index}>{v}</p>)}</section>:null}
    <Dialog open={Boolean(detail)} onOpenChange={open=>{if(!open)setDetail(null)}}><DialogContent className={styles.detailDialog} onCloseAutoFocus={event=>{event.preventDefault();requestAnimationFrame(()=>{const opener=detailOpener.current;(opener?.isConnected&&!opener.matches(':disabled')?opener:document.querySelector<HTMLElement>('[data-diag-details-trigger]'))?.focus()})}}><DialogHeader><DialogTitle>{detail?.label}</DialogTitle><DialogDescription>{detail?.kind==='citations'?'本次检索返回的来源文档与片段':'本次检索预览返回的字段'}</DialogDescription></DialogHeader>{detail?.kind==='citations'?<CitationOutput data={detail.data} documents={c.documents}/>:<pre className={styles.rawContent}>{detail?.data===null||detail?.data===undefined?'当前响应未返回这些字段。':JSON.stringify(detail?.data,null,2)}</pre>}</DialogContent></Dialog>
  </>
}
