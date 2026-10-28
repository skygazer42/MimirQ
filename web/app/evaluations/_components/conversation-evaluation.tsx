'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { evaluationApi, chatApi, type RagasRun, type RagasRunDetail } from '@/lib/api'
import type { Conversation } from '@/types'
import { queryKeys } from '@/lib/query-keys'
import { formatApiError } from '@/lib/api-errors'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { getRagasMetricOptions } from '@/components/evaluation/ragas-metric-selector'
import { AlertCircle, ArrowLeft, Check, CheckCircle2, ChevronLeft, ChevronRight, Clock3, Download, FileText, History, Loader2, MessageSquare, Play, RefreshCw, Search, SlidersHorizontal } from '@/components/icons'
import { Link } from '@/i18n/navigation'
import { cn } from '@/lib/utils'
import { displayDate, hasLowScore, itemContexts, metricName, metricStatistics, numericScore, runDuration } from './evaluation-model'
import styles from '../evaluations.module.css'

const EMPTY_CONVERSATIONS: Conversation[]=[]
const EMPTY_RUNS: RagasRun[]=[]
const EMPTY_ITEMS: RagasRunDetail['items']=[]
const DETAIL_OPTIONS={include_items:true,include_contexts:true} as const
function RunStatus({status}:{status?:string}) {
  if(!status)return null
  const completed=status==='completed', failed=status==='failed'
  const Icon=completed?CheckCircle2:failed?AlertCircle:Clock3
  return <span className={cn(styles.status,completed?styles.success:failed?styles.danger:styles.processing)}><Icon aria-hidden="true" />{completed?'已完成':failed?'失败':status==='pending'?'待运行':'运行中'}</span>
}
function Score({value,bars=false}:{value:unknown;bars?:boolean}) {
  const number=numericScore(value)
  return <span className={cn(styles.score,number!==null&&number<.8&&styles.lowScore)}>{number===null?'—':number.toFixed(2)}{bars&&number!==null&&<i className={styles.track} aria-hidden="true"><i style={{width:`${Math.max(0,Math.min(1,number))*100}%`}} /></i>}</span>
}

export function ConversationEvaluation({active}:{active:boolean}) {
  const searchParams=useSearchParams()
  const deepLink=searchParams.get('conversation_id')?.trim()||''
  const [conversationId,setConversationId]=useState(deepLink)
  const [runChoice,setRunChoice]=useState({conversationId:'',id:''})
  const [sampleChoice,setSampleChoice]=useState({runId:'',id:''})
  const [metricKeys,setMetricKeys]=useState(['faithfulness','response_relevancy'])
  const [maxTurns,setMaxTurns]=useState('20')
  const [skipEmpty,setSkipEmpty]=useState(true)
  const [onlyLow,setOnlyLow]=useState(false)
  const [search,setSearch]=useState('')
  const [conversationSearch,setConversationSearch]=useState('')
  const [evidenceFilter,setEvidenceFilter]=useState('all')
  const [pickerOpen,setPickerOpen]=useState(false)
  const [recordsOpen,setRecordsOpen]=useState(false)
  const [recordSearch,setRecordSearch]=useState('')
  const [isStarting,setIsStarting]=useState(false)
  const startingRef=useRef(false)
  const [mobileReader,setMobileReader]=useState(false)
  const readerRef=useRef<HTMLHeadingElement>(null)
  const readerScrollRef=useRef<HTMLDivElement>(null)
  const selectedButtonRef=useRef<HTMLButtonElement|null>(null)
  useEffect(()=>{if(deepLink)setConversationId(deepLink)},[deepLink])
  const conversationsQuery=useQuery({queryKey:queryKeys.chat.conversations({limit:100}),queryFn:()=>chatApi.listConversations({limit:100}),enabled:active})
  const conversations=conversationsQuery.data?.items??EMPTY_CONVERSATIONS
  const scopedId=conversationId||conversations[0]?.id||''
  const currentConversation=conversations.find(conversation=>conversation.id===scopedId)
  const messagesQuery=useQuery({queryKey:queryKeys.chat.messages(scopedId),queryFn:()=>chatApi.getMessages(scopedId,{limit:200}),enabled:active&&Boolean(scopedId)})
  const ids=useMemo(()=>conversations.map(conversation=>conversation.id),[conversations])
  const readinessQuery=useQuery({queryKey:queryKeys.evaluations.ragasConversationReadiness(ids),queryFn:()=>evaluationApi.getRagasConversationReadiness({conversation_ids:ids}),enabled:active&&ids.length>0,staleTime:60000})
  const readiness=useMemo(()=>new Map((readinessQuery.data?.items||[]).map(item=>[item.conversation_id,item])),[readinessQuery.data?.items])
  const runListParams=useMemo(()=>({limit:50,...(scopedId?{conversation_id:scopedId}:{})}),[scopedId])
  const runsQuery=useQuery({queryKey:queryKeys.evaluations.ragasRuns(runListParams),queryFn:()=>evaluationApi.listRagasRuns(runListParams),enabled:active&&Boolean(scopedId)})
  const runs=runsQuery.data?.items??EMPTY_RUNS
  const selectedRunId=runChoice.conversationId===scopedId?runChoice.id:runs[0]?.id||''
  const detailQuery=useQuery({queryKey:queryKeys.evaluations.ragasRunDetail(selectedRunId,DETAIL_OPTIONS),queryFn:()=>evaluationApi.getRagasRun(selectedRunId,DETAIL_OPTIONS),enabled:active&&Boolean(selectedRunId),refetchInterval:query=>active&&['pending','running'].includes(query.state.data?.run?.status||'')?2000:false})
  const detail=detailQuery.data?.run.id===selectedRunId?detailQuery.data:null
  const selectedRun=detail?.run||runs.find(run=>run.id===selectedRunId)
  const items=detail?.items??EMPTY_ITEMS
  const resultMetricKeys=selectedRun?.metrics?.length?selectedRun.metrics:metricKeys
  const statistics=useMemo(()=>metricStatistics(detail,resultMetricKeys),[detail,resultMetricKeys])
  const lowCount=items.filter(item=>hasLowScore(item,resultMetricKeys)).length
  const visibleItems=useMemo(()=>items.filter(item=>(!onlyLow||hasLowScore(item,resultMetricKeys))&&(!search.trim()||item.user_input.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))),[items,onlyLow,resultMetricKeys,search])
  const selectedItem=visibleItems.find(item=>sampleChoice.runId===selectedRunId&&item.id===sampleChoice.id)||visibleItems[0]||null
  const selectedIndex=selectedItem?visibleItems.indexOf(selectedItem):-1
  const assistantMessages=(messagesQuery.data?.messages||[]).filter(message=>message.role==='assistant')
  const evaluableTurns=assistantMessages.filter(message=>(message.citations?.length||0)>0).length
  const checkingEvidence=Boolean(scopedId)&&messagesQuery.isPending
  const missingEvidence=Boolean(scopedId)&&messagesQuery.isSuccess&&evaluableTurns===0
  const validTurns=Number.isInteger(Number(maxTurns))&&Number(maxTurns)>=1&&Number(maxTurns)<=200
  const canStart=Boolean(scopedId)&&messagesQuery.isSuccess&&!missingEvidence&&metricKeys.length>0&&validTurns&&!isStarting
  const filteredConversations=conversations.filter(conversation=>{
    const item=readiness.get(conversation.id)
    return (!conversationSearch.trim()||(conversation.title||conversation.id).toLocaleLowerCase().includes(conversationSearch.trim().toLocaleLowerCase()))&&(evidenceFilter==='all'||(item&&(evidenceFilter==='ready'?item.is_evaluable:!item.is_evaluable)))
  })
  const runError=String(selectedRun?.error_message||'').trim()
  const deterministic=selectedRun?.summary?.mode==='deterministic_conversation'
  function chooseRun(id:string) { setRunChoice({conversationId:scopedId,id});setSearch('');setOnlyLow(false);setMobileReader(false);setRecordsOpen(false) }
  function chooseSample(item:RagasRunDetail['items'][number],button?:HTMLButtonElement) {
    setSampleChoice({runId:selectedRunId,id:item.id});setMobileReader(true)
    if(button)selectedButtonRef.current=button
    requestAnimationFrame(()=>{readerScrollRef.current?.scrollTo({top:0});readerRef.current?.focus({preventScroll:true})})
  }
  function returnToMatrix() { setMobileReader(false);requestAnimationFrame(()=>selectedButtonRef.current?.focus()) }
  async function start() {
    if(!canStart||startingRef.current)return
    startingRef.current=true;setIsStarting(true)
    try {
      const run=await evaluationApi.createRagasRun({conversation_id:scopedId,metrics:metricKeys,max_turns:Number(maxTurns),skip_empty_contexts:skipEmpty,include_contexts_in_response:false})
      chooseRun(run.id);toast.success('评测已开始');await runsQuery.refetch()
    } catch(error) { toast.error(formatApiError(error,'启动评测失败')) }
    finally {startingRef.current=false;setIsStarting(false)}
  }
  function exportItems() {
    if(!detail)return
    const url=URL.createObjectURL(new Blob([JSON.stringify(detail.items,null,2)],{type:'application/json;charset=utf-8'}))
    const anchor=document.createElement('a');anchor.href=url;anchor.download=`ragas-run-items.${selectedRunId}.json`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast.success('结果已导出')
  }
  const reason=!scopedId?'选择对话后开始':checkingEvidence?'正在检查引用':messagesQuery.isError?'引用读取失败，请重试':missingEvidence?'这条对话没有引用上下文':!metricKeys.length?'至少选择一项指标':!validTurns?'最近轮次应为 1–200 的整数':''
  const contextCount=items.reduce((sum,item)=>sum+Math.max(itemContexts(item).length,item.citations?.length||0),0)
  return <div className={styles.conversation} data-evaluation-matrix>
    <div className={styles.runbar}>
      <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
        <DialogTrigger asChild><Button variant="ghost" className={styles.conversationPicker} disabled={isStarting}><MessageSquare aria-hidden="true" /><span>{currentConversation?.title||'选择对话'}</span><ChevronRight aria-hidden="true" /></Button></DialogTrigger>
        <DialogContent className={styles.dialog}>
          <DialogHeader><DialogTitle>选择对话</DialogTitle><DialogDescription>选择已有问答，使用它的回答和引用进行评测。</DialogDescription></DialogHeader>
          <div className={styles.dialogToolbar}><Search aria-hidden="true" /><Input aria-label="搜索对话" placeholder="搜索对话" value={conversationSearch} onChange={event=>setConversationSearch(event.target.value)} /></div>
          <div className={styles.viewFilters}>{[['all','全部'],['ready','可评测'],['missing','缺证据']].map(([id,label])=><button key={id} type="button" aria-pressed={evidenceFilter===id} onClick={()=>setEvidenceFilter(id)}>{label}</button>)}</div>
          <div className={styles.dialogList}>
            {conversationsQuery.isError?<div className={styles.state}><p>对话加载失败</p><Button variant="outline" onClick={()=>conversationsQuery.refetch()}>重试</Button></div>:conversationsQuery.isPending?<div className={styles.state}><Loader2 className="animate-spin" />正在加载对话…</div>:filteredConversations.length?filteredConversations.map(conversation=>{
              const evidence=readiness.get(conversation.id)
              return <button key={conversation.id} type="button" className={styles.listItem} aria-pressed={scopedId===conversation.id} onClick={()=>{setConversationId(conversation.id);setSearch('');setOnlyLow(false);setMobileReader(false);setPickerOpen(false)}}><span><strong>{conversation.title||'未命名对话'}</strong><small>{displayDate(conversation.created_at)}</small></span><span className={cn(styles.listHint,evidence&&!evidence.is_evaluable&&styles.lowScore)}>{evidence?evidence.is_evaluable?`${evidence.evaluable_turns} 个可评轮次`:'缺少引用':readinessQuery.isError?'证据状态未知':'检查引用中'}{scopedId===conversation.id&&<Check aria-hidden="true" />}</span></button>
            }):<div className={styles.state}><p>{conversationSearch?'没有匹配的对话':'没有符合条件的对话'}</p>{evidenceFilter!=='all'&&<Button variant="outline" onClick={()=>setEvidenceFilter('all')}>查看全部</Button>}<Link href="/">新对话</Link></div>}
          </div>
        </DialogContent>
      </Dialog>
      <div className={styles.runMeta}><span>{selectedRunId?selectedRunId.slice(0,12):'尚未运行'}</span><RunStatus status={selectedRun?.status} /><span>{displayDate(selectedRun?.created_at)}</span>{runDuration(selectedRun?.started_at,selectedRun?.finished_at)&&<span>耗时 {runDuration(selectedRun?.started_at,selectedRun?.finished_at)}</span>}</div>
      <div className={styles.runActions}>
        <Dialog open={recordsOpen} onOpenChange={setRecordsOpen}><DialogTrigger asChild><Button variant="outline"><History aria-hidden="true" /><span>运行记录 {runsQuery.data?.total??runs.length}</span></Button></DialogTrigger><DialogContent className={styles.dialog}>
          <DialogHeader><DialogTitle>运行记录</DialogTitle><DialogDescription>{currentConversation?.title||'当前对话'}的最近 50 次运行</DialogDescription></DialogHeader>
          <div className={styles.dialogToolbar}><Search aria-hidden="true" /><Input aria-label="搜索运行记录" placeholder="搜索运行编号或状态" value={recordSearch} onChange={event=>setRecordSearch(event.target.value)} /><Button variant="ghost" aria-label="刷新运行记录" disabled={runsQuery.isFetching} onClick={()=>runsQuery.refetch()}><RefreshCw /></Button></div>
          <div className={styles.dialogList}>{runsQuery.isError?<div className={styles.state}><p>运行记录加载失败</p><Button variant="outline" onClick={()=>runsQuery.refetch()}>重试</Button></div>:runsQuery.isPending?<div className={styles.state}>正在加载记录…</div>:runs.filter(run=>!recordSearch.trim()||`${run.id} ${run.status}`.includes(recordSearch.trim())).map(run=><button key={run.id} type="button" className={styles.listItem} aria-pressed={selectedRunId===run.id} onClick={()=>chooseRun(run.id)}><span><strong>{run.id}</strong><small>{displayDate(run.created_at)} · {run.metrics.map(metricName).join('／')}</small></span><RunStatus status={run.status} /></button>)}{!runsQuery.isPending&&!runsQuery.isError&&!runs.length&&<div className={styles.state}><p>暂无运行记录</p><p>运行完成后，可在这里切换查看结果。</p></div>}</div>
        </DialogContent></Dialog>
        <Button variant="ghost" aria-label="导出结果" title="导出结果" disabled={!detail?.items.length||detailQuery.isFetching} onClick={exportItems}><Download aria-hidden="true" /></Button>
        <Button className={styles.primary} disabled={!canStart} onClick={start}>{isStarting?<Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />:<Play aria-hidden="true" />}<span>{isStarting?'启动中…':'开始评测'}</span></Button>
      </div>
    </div>
    <div className={styles.parameterbar}>
      <span>下次评测 <b>{metricKeys.length} 项指标</b></span><span>最近 <b>{maxTurns||'—'} 轮</b></span><span className={styles.skip}>{skipEmpty&&<Check aria-hidden="true" />}{skipEmpty?'跳过无引用轮次':'包括无引用轮次'}</span>
      <Dialog><DialogTrigger asChild><Button variant="ghost"><SlidersHorizontal aria-hidden="true" />评测参数</Button></DialogTrigger><DialogContent className={styles.configDialog}>
        <DialogHeader><DialogTitle>评测参数</DialogTitle><DialogDescription>参数用于下一次运行，已完成的结果保持不变。</DialogDescription></DialogHeader>
        <div className={styles.configBody}><fieldset><legend>评测指标</legend>{getRagasMetricOptions('conversation').map(metric=><label key={metric.key} className={styles.metricOption}><Checkbox checked={metricKeys.includes(metric.key)} disabled={isStarting} onCheckedChange={checked=>setMetricKeys(previous=>checked===true?[...new Set([...previous,metric.key])]:previous.filter(key=>key!==metric.key))} /><span><strong>{metricName(metric.key)}</strong><small>{metric.hint}</small></span></label>)}{!metricKeys.length&&<p className={styles.formError}>至少选择一项指标。</p>}</fieldset>
          <label className={styles.numberField}>最近轮次<Input type="number" aria-label="最近轮次" min={1} max={200} step={1} value={maxTurns} disabled={isStarting} aria-invalid={!validTurns} onChange={event=>setMaxTurns(event.target.value)} /></label>{!validTurns&&<p className={styles.formError}>请输入 1–200 的整数。</p>}
          <label className={styles.checkboxField}><Checkbox checked={skipEmpty} disabled={isStarting} onCheckedChange={value=>setSkipEmpty(value===true)} />跳过无引用轮次</label>
        </div><div className={styles.dialogFooter}><Button variant="ghost" disabled={isStarting} onClick={()=>{setMetricKeys(['faithfulness','response_relevancy']);setMaxTurns('20');setSkipEmpty(true)}}>恢复默认</Button><DialogClose asChild><Button className={styles.primary}>完成</Button></DialogClose></div>
      </DialogContent></Dialog>
    </div>
    {reason&&<div className={cn(styles.notice,missingEvidence&&styles.warning)} role={messagesQuery.isError?'alert':'status'}>{checkingEvidence?<Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />:<AlertCircle aria-hidden="true" />}<span>{reason}</span>{messagesQuery.isError&&<Button variant="ghost" size="sm" onClick={()=>messagesQuery.refetch()}>重试</Button>}{(!scopedId||missingEvidence)&&<Button variant="ghost" size="sm" onClick={()=>setPickerOpen(true)}>{missingEvidence?'更换对话':'选择对话'}</Button>}</div>}
    {runsQuery.isError&&<div className={styles.notice} role="alert"><AlertCircle/><span>运行记录加载失败</span><Button variant="ghost" size="sm" onClick={()=>runsQuery.refetch()}>重试</Button></div>}
    {deterministic&&<div className={styles.notice}><span>确定性证据校验</span><span className={styles.muted}>{selectedRun?.summary?.ragas_skipped_reason==='ragas_wall_timeout'?'RAGAS 超时，当前分数来自证据一致性校验。':'当前分数来自证据一致性校验。'}</span></div>}
    <div className={styles.matrixWorkspace} data-mobile-reader={mobileReader}>
      <section className={styles.matrixPane} aria-label="样本矩阵">
        <div className={styles.matrixToolbar}><h2>样本矩阵 <small>{items.length} 个样本</small></h2><div className={styles.viewFilters}><button type="button" aria-pressed={!onlyLow} onClick={()=>setOnlyLow(false)}>全部</button><button type="button" aria-pressed={onlyLow} onClick={()=>setOnlyLow(true)}>低分 {lowCount}</button></div><div className={styles.sampleSearch}><Search aria-hidden="true" /><Input type="search" aria-label="搜索评测问题" placeholder="搜索问题" value={search} onChange={event=>setSearch(event.target.value)} /></div></div>
        <div className={styles.tableScroll}>
          <table className={styles.matrixTable} aria-label="逐轮评分矩阵"><colgroup><col className={styles.indexColumn}/><col/>{resultMetricKeys.map(key=><col key={key} className={cn(styles.scoreColumn,resultMetricKeys.length<3&&styles.wideScoreColumn)}/>)}<col className={styles.contextColumn}/></colgroup><thead><tr><th scope="col">#</th><th scope="col">问题</th>{resultMetricKeys.map(key=><th scope="col" key={key}>{metricName(key)}</th>)}<th scope="col">引用</th></tr></thead><tbody>
            <tr className={styles.meanRow}><td /><th scope="row"><strong>运行均值</strong><small>{items.length?`${items.length} 个样本`:'尚无样本'}</small></th>{statistics.map(metric=><td key={metric.key}><Score value={metric.mean}/></td>)}<td>{items.length?`${contextCount} 条`:'—'}</td></tr>
            {visibleItems.map(item=><tr key={item.id} data-sample-row data-selected={selectedItem?.id===item.id}><td>{String(item.turn_index).padStart(2,'0')}</td><th scope="row"><button type="button" onClick={event=>chooseSample(item,event.currentTarget)} aria-pressed={selectedItem?.id===item.id}>{item.user_input||'未记录问题'}</button>{hasLowScore(item,resultMetricKeys)&&<small className={styles.lowScore}>低分</small>}</th>{resultMetricKeys.map(key=><td key={key}><Score value={item.scores?.[key]} bars/></td>)}<td>{Math.max(itemContexts(item).length,item.citations?.length||0)} 条</td></tr>)}
          </tbody></table>
          {detailQuery.isError?<div className={styles.state} role="alert"><AlertCircle/><h3>评测结果加载失败</h3><p>{formatApiError(detailQuery.error,'无法读取结果')}</p><Button variant="outline" onClick={()=>detailQuery.refetch()}>重试</Button></div>:detailQuery.isPending&&selectedRunId?<div className={styles.state} role="status"><Loader2 className="animate-spin motion-reduce:animate-none"/><p>正在读取评测结果…</p></div>:!visibleItems.length?<div className={styles.state}><h3>{items.length?'没有匹配的样本':selectedRun?.status==='failed'?'评测失败':selectedRun?.status==='running'||selectedRun?.status==='pending'?'正在评测':'暂无评测结果'}</h3><p>{items.length?'调整搜索条件或查看全部样本。':runError||(!selectedRunId?'选择包含引用的对话，点击「开始评测」。':selectedRun?.status==='completed'?'这次运行没有返回逐轮样本。':'完成后将自动显示逐轮评分。')}</p>{items.length>0&&<Button variant="outline" onClick={()=>{setSearch('');setOnlyLow(false)}}>查看全部样本</Button>}</div>:null}
        </div>
        <footer className={styles.footer}><span>评分范围 0–1</span><span>低分：任一指标 &lt; 0.80</span><span>{detailQuery.isFetching&&!detailQuery.isPending?'更新中…':`${visibleItems.length} / ${items.length} 个样本`}</span></footer>
      </section>
      <aside className={styles.reader} aria-label="样本阅读区" role="region">
        <div className={styles.readerToolbar}><Button variant="ghost" className={styles.mobileBack} aria-label="返回样本矩阵" onClick={returnToMatrix}><ArrowLeft/></Button><span>样本 {selectedItem?String(selectedItem.turn_index).padStart(2,'0'):'—'}</span>{selectedItem&&hasLowScore(selectedItem,resultMetricKeys)&&<span className={styles.lowScore}>低分</span>}<div className={styles.readerNav}><small>{selectedItem?`${selectedIndex+1} / ${visibleItems.length}`:'0 / 0'}</small><Button variant="ghost" aria-label="上一个样本" disabled={selectedIndex<=0} onClick={()=>chooseSample(visibleItems[selectedIndex-1])}><ChevronLeft/></Button><Button variant="ghost" aria-label="下一个样本" disabled={selectedIndex<0||selectedIndex>=visibleItems.length-1} onClick={()=>chooseSample(visibleItems[selectedIndex+1])}><ChevronRight/></Button></div></div>
        <div className={styles.readerScroll} ref={readerScrollRef}>{selectedItem?<div key={`${selectedRunId}:${selectedItem.id}`} className={styles.readerContent} data-evaluation-reader-item={selectedItem.id}>
          <h3 ref={readerRef} tabIndex={-1}>{selectedItem.user_input||'未记录问题'}</h3>
          <dl className={styles.readerScores}>{resultMetricKeys.map(key=><div key={key}><dt>{metricName(key)}</dt><dd><Score value={selectedItem.scores?.[key]}/></dd></div>)}</dl>
          <section className={styles.readerSection}><h4>回答</h4><p>{selectedItem.response||'未记录回答'}</p></section>
          <section className={styles.readerSection}><h4><FileText aria-hidden="true"/>引用上下文 <small>{Math.max(itemContexts(selectedItem).length,selectedItem.citations?.length||0)} 条</small></h4>{itemContexts(selectedItem).length?itemContexts(selectedItem).map((text,index)=><blockquote key={index}><span>{String(index+1).padStart(2,'0')}</span><p>{text}</p></blockquote>):<p className={styles.muted}>{selectedItem.citations?.length?'这次运行保留了引用记录，但没有保存上下文正文。':'这个样本没有引用上下文。'}</p>}</section>
          {selectedItem.citations?.length>0&&<details className={styles.sourceDetails}><summary>引用记录</summary><pre>{JSON.stringify(selectedItem.citations,null,2)}</pre></details>}
          <details className={styles.sourceDetails}><summary>运行统计</summary><dl className={styles.runStats}><div><dt>令牌消耗</dt><dd>{numericScore(selectedRun?.summary?.total_tokens)??'—'}</dd></div><div><dt>模型成本</dt><dd>{numericScore(selectedRun?.summary?.total_cost)!==null?`¥${Number(selectedRun?.summary?.total_cost).toFixed(4)}`:'—'}</dd></div></dl><table aria-label="指标统计"><thead><tr><th>指标</th><th>P50</th><th>P90</th><th>通过率</th></tr></thead><tbody>{statistics.map(row=><tr key={row.key}><th>{row.label}</th><td>{row.p50?.toFixed(2)??'—'}</td><td>{row.p90?.toFixed(2)??'—'}</td><td>{row.passRate!==null?`${Math.round(row.passRate*100)}%`:'—'}</td></tr>)}</tbody></table></details>
        </div>:<div className={styles.readerEmpty}><FileText aria-hidden="true"/><p>选择一个样本</p><span>在这里核对回答与引用</span></div>}</div>
      </aside>
    </div>
  </div>
}
