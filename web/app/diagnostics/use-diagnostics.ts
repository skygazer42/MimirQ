'use client'

import { useMemo,useRef,useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { datasetApi } from '@/lib/api/datasets'
import { documentApi } from '@/lib/api/documents'
import { healthApi } from '@/lib/api/health'
import { observabilityApi } from '@/lib/api/observability'
import { ragApi,retrievalApi } from '@/lib/api/rag'
import { useBackendHealth } from '@/hooks/use-backend-health'
import { useBackendMetaDetails } from '@/hooks/use-backend-meta'
import { buildRetrievalConfigHashRequest,hasDatasetRagContract } from '@/lib/dataset-rag-contract'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { dependencyState,metricRows,previewSummary,record,text,validateParams,type JsonRecord,type PreviewResult,type ScopeSnapshot,type Verdict } from './diagnostics-model'

export const ALL_DATASETS='__all_datasets__'
export type Probe<T>={status:'idle'|'running'|'success'|'error';result:T|null;error:string}
export type ScopedSnapshot={data:JsonRecord;scope:ScopeSnapshot;params:{first:string;second:string};finishedAt:number}
const emptyProbe=<T>():Probe<T>=>({status:'idle',result:null,error:''})

export function useDiagnostics() {
  const health=useBackendHealth(),meta=useBackendMetaDetails()
  const ready=useQuery({queryKey:queryKeys.diagnostics.ready,queryFn:()=>healthApi.ready(),staleTime:10_000,refetchInterval:30_000,refetchOnWindowFocus:false,retry:1})
  const deps=useQuery({queryKey:queryKeys.diagnostics.deps,queryFn:()=>observabilityApi.getDepsDiagnosticsSnapshot(),staleTime:15_000,refetchOnWindowFocus:false,retry:1})
  const online=useQuery({queryKey:queryKeys.diagnostics.onlineQuality({window_minutes:240,bucket_minutes:5}),queryFn:()=>observabilityApi.getOnlineQualitySummary({window_minutes:240,bucket_minutes:5}),staleTime:30_000,refetchOnWindowFocus:false,retry:1})
  const datasetsQuery=useQuery({queryKey:queryKeys.datasets.exhaustive({purpose:'diagnostics'}),queryFn:()=>datasetApi.listAll(),staleTime:30_000})
  const [datasetChoice,setDatasetChoice]=useState<string|null>(null)
  const [documentIds,setDocumentIds]=useState<string[]>([])
  const [query,setQuery]=useState('')
  const [tab,setTab]=useState('retrieval')
  const [detailsOpen,setDetailsOpen]=useState(false),[servicesOpen,setServicesOpen]=useState(false)
  const [preview,setPreview]=useState<Probe<PreviewResult>>(emptyProbe)
  const [drift,setDrift]=useState<Probe<ScopedSnapshot>>(emptyProbe)
  const [perf,setPerf]=useState<Probe<ScopedSnapshot>>(emptyProbe)
  const [driftParams,setDriftParams]=useState({first:'200',second:'0.05'})
  const [perfParams,setPerfParams]=useState({first:'10',second:'2'})
  const [driftErrors,setDriftErrors]=useState<Record<string,string>>({}),[perfErrors,setPerfErrors]=useState<Record<string,string>>({})
  const [visibleMetrics,setVisibleMetrics]=useState(()=>metricRows(null).map(metric=>metric.key))
  const locks=useRef({preview:false,drift:false,perf:false})
  const openers=useRef<{details:HTMLElement|null;services:HTMLElement|null}>({details:null,services:null})
  const datasets=datasetsQuery.data??[]
  const datasetId=datasetChoice===ALL_DATASETS?'':datasetChoice??datasets[0]?.id??''
  const activeDataset=useQuery({queryKey:queryKeys.datasets.detail(datasetId),enabled:Boolean(datasetId),queryFn:()=>datasetApi.get(datasetId),staleTime:30_000})
  const documentsQuery=useQuery({queryKey:queryKeys.documents.list({dataset_id:datasetId,limit:200,order_by:'created_at',order_dir:'desc'}),enabled:Boolean(datasetId),queryFn:()=>documentApi.list({skip:0,limit:200,dataset_id:datasetId,order_by:'created_at',order_dir:'desc'}),staleTime:15_000})
  const documents=documentsQuery.data?.items??[]
  const dataset=activeDataset.data??datasets.find(d=>d.id===datasetId)??null
  const scopeBusy=preview.status==='running'||drift.status==='running'
  const missingDocuments=documentIds.some(id=>!documents.some(d=>d.id===id))
  const missingDataset=Boolean(datasetId&&!datasetsQuery.isPending&&!datasetsQuery.isError&&!datasets.some(d=>d.id===datasetId))
  const contract=activeDataset.data?.rag_defaults
  const contractReason=!datasetId?'未限定数据集，不读取数据集检索配置。':activeDataset.isError?'数据集检索配置获取失败。':!hasDatasetRagContract(contract)?'数据集未配置检索参数，链路配置暂不可用。':null
  const vectorBackend=text(record(record(health.data?.payload).vector).backend)??text(record(health.data?.payload).vector_backend)??text(record(record(meta.data).features).vector_backend)
  const canDrift=vectorBackend===null||vectorBackend==='milvus'
  const scope=():ScopeSnapshot=>({datasetId,datasetName:datasetId?(dataset?.name??datasetId):'全部数据集',documentIds:[...documentIds],documentNames:documentIds.map(id=>documents.find(d=>d.id===id)?.filename??id),query:query.trim()})
  const services=useMemo(()=>{
    const h=record(health.data?.payload),d=record(deps.data)
    const healthState:Verdict=health.isError?{label:'获取失败',tone:'danger'}:health.isPending?{label:'检查中',tone:'neutral'}:record(health.data?.payload).ok===true?{label:'已连接',tone:'success'}:{label:'异常',tone:'danger'}
    return [{key:'api',name:'服务 API',...healthState},
      {key:'postgres',name:'PostgreSQL',...dependencyState(h.database,d.postgres)},
      {key:'vector',name:vectorBackend==='milvus'?'Milvus':vectorBackend==='memory'?'向量后端':vectorBackend??'向量后端',...dependencyState(h.vector,d.milvus)},
      {key:'redis',name:'Redis',...dependencyState(h.redis,d.redis)},
      {key:'minio',name:'MinIO',...dependencyState(h.minio,d.minio)}]
  },[health.data,health.isError,health.isPending,deps.data,vectorBackend])
  const systemState:Verdict=health.isPending||ready.isPending?{label:'检查中',tone:'neutral'}:health.isError||ready.isError?{label:'状态获取失败',tone:'warning'}:record(health.data?.payload).ok===true&&record(ready.data).ok===true?{label:'服务可用',tone:'success'}:{label:'服务需排查',tone:'danger'}
  const changeDataset=(value:string)=>{
    if(scopeBusy)return
    setDatasetChoice(value);setDocumentIds([]);setPreview(emptyProbe());setDrift(emptyProbe());setDriftErrors({})
  }
  const changeDocuments=(ids:string[])=>{if(locks.current.preview)return;setDocumentIds(ids);setPreview(emptyProbe())}
  const changeQuery=(value:string)=>{if(locks.current.preview)return;setQuery(value);setPreview(emptyProbe())}
  async function runPreview() {
    if(locks.current.preview||!query.trim()||missingDataset||missingDocuments||datasetsQuery.isPending||Boolean(datasetId&&activeDataset.isPending))return
    const captured=scope(),configRequest=buildRetrievalConfigHashRequest(contract)
    locks.current.preview=true;setPreview(previous=>({...previous,status:'running',error:''}))
    try {
      const [main,explain,hash]=await Promise.allSettled([
        ragApi.promptPreview({query:captured.query,dataset_id:captured.datasetId||undefined,document_ids:captured.documentIds,structured_output:false}),
        !contractReason&&configRequest?retrievalApi.explain({query:captured.query,dataset_id:captured.datasetId,document_ids:captured.documentIds,rag_config:configRequest.rag_config,retrieval_only:true,top_citations_limit:8}):Promise.resolve(null),
        !contractReason&&configRequest?retrievalApi.configHash(configRequest):Promise.resolve(null),
      ])
      if(main.status==='rejected')throw main.reason
      const partialErrors=[explain.status==='rejected'?`链路详情：${formatApiError(explain.reason,'获取失败')}`:null,hash.status==='rejected'?`配置签名：${formatApiError(hash.reason,'获取失败')}`:null].filter((v):v is string=>Boolean(v))
      setPreview({status:'success',error:'',result:{scope:captured,preview:main.value,explain:explain.status==='fulfilled'&&explain.value?record(explain.value):null,configHash:hash.status==='fulfilled'&&hash.value?record(hash.value):null,contractReason,partialErrors,finishedAt:Date.now()}})
      if(partialErrors.length)toast.warning('预览已返回，部分链路信息未取得。');else toast.success('检索预览已返回')
    }catch(error){const message=formatApiError(error,'检索预览失败');setPreview(previous=>({...previous,status:'error',error:message}));toast.error(message)}
    finally{locks.current.preview=false}
  }
  async function runDrift() {
    if(locks.current.drift||!canDrift||missingDataset||datasetsQuery.isPending)return
    const errors=validateParams('drift',driftParams.first,driftParams.second);setDriftErrors(errors)
    if(Object.keys(errors).length){document.getElementById(errors.first?'drift-samples':'drift-threshold')?.focus();return}
    const captured=scope(),params={...driftParams};locks.current.drift=true;setDrift(previous=>({...previous,status:'running',error:''}))
    try{const data=await observabilityApi.getEmbeddingDriftSnapshot({dataset_id:captured.datasetId||undefined,sample_n:Number(params.first),drift_threshold:Number(params.second)});setDrift({status:'success',error:'',result:{data,scope:{...captured,documentIds:[],documentNames:[],query:''},params,finishedAt:Date.now()}});if(data.ok===false)toast.warning('漂移检查未完成');else toast.success('漂移检查已返回')}
    catch(error){const message=formatApiError(error,'漂移检查失败');setDrift(previous=>({...previous,status:'error',error:message}));toast.error(message)}finally{locks.current.drift=false}
  }
  async function runPerf() {
    if(locks.current.perf)return
    const errors=validateParams('perf',perfParams.first,perfParams.second);setPerfErrors(errors)
    if(Object.keys(errors).length){document.getElementById(errors.first?'perf-iterations':'perf-timeout')?.focus();return}
    const params={...perfParams};locks.current.perf=true;setPerf(previous=>({...previous,status:'running',error:''}))
    try{const data=await observabilityApi.runPerfSuite({iterations:Number(params.first),timeout_sec:Number(params.second)});setPerf({status:'success',error:'',result:{data,scope:{datasetId:'',datasetName:'全局 API',documentIds:[],documentNames:[],query:''},params,finishedAt:Date.now()}});toast.success('性能门禁已返回')}
    catch(error){const message=formatApiError(error,'性能门禁失败');setPerf(previous=>({...previous,status:'error',error:message}));toast.error(message)}finally{locks.current.perf=false}
  }
  const refreshStatus=()=>Promise.allSettled([health.refetch(),meta.refetch(),ready.refetch(),deps.refetch(),online.refetch()])
  const rawSummary={dataset_id:datasetId||null,document_ids:documentIds,display_metrics:visibleMetrics,rag_preview:preview.result?.preview??null,retrieval_explain:preview.result?.explain??null,retrieval_config_hash:preview.result?.configHash??null,preview_scope:preview.result?.scope??null,preview_error:preview.error||null,embedding_drift:drift.result?.data??null,drift_scope:drift.result?.scope??null,perf_suite:perf.result?.data??null,perf_scope:perf.result?.scope??null,dependencies:deps.data??null,ready:ready.data??null,health:health.data?.payload??null,online_quality:online.data??null}
  const copySummary=async()=>{try{await navigator.clipboard.writeText(JSON.stringify(rawSummary,null,2));toast.success('诊断摘要已复制')}catch{toast.error('无法复制，请在原始响应中选择文本。')}}
  return {tab,setTab,query,changeQuery,datasetId,dataset,datasetsQuery,datasets,activeDataset,changeDataset,documentIds,changeDocuments,documents,documentsQuery,missingDocuments,missingDataset,scopeBusy,
    health,meta,ready,deps,online,vectorBackend,canDrift,services,systemState,refreshStatus,statusRefreshing:health.isFetching||meta.isFetching||ready.isFetching||deps.isFetching||online.isFetching,
    preview,drift,perf,runPreview,runDrift,runPerf,contractReason,summary:previewSummary(preview.result),metrics:metricRows(preview.result?.preview??null),
    driftParams,perfParams,driftErrors,perfErrors,changeDriftParams:(value:typeof driftParams)=>{if(!locks.current.drift){setDriftParams(value);setDrift(emptyProbe());setDriftErrors({})}},changePerfParams:(value:typeof perfParams)=>{if(!locks.current.perf){setPerfParams(value);setPerf(emptyProbe());setPerfErrors({})}},
    visibleMetrics,toggleMetric:(key:string)=>setVisibleMetrics(previous=>previous.includes(key)?previous.filter(k=>k!==key):[...previous,key]),clearPreview:()=>{if(!locks.current.preview){setQuery('');setPreview(emptyProbe())}},
    detailsOpen,setDetailsOpen,servicesOpen,setServicesOpen,rawSummary,copySummary,
    openDetails:(opener?:HTMLElement)=>{openers.current.details=opener??(document.activeElement instanceof HTMLElement?document.activeElement:null);setDetailsOpen(true)},
    openServices:(opener?:HTMLElement)=>{openers.current.services=opener??(document.activeElement instanceof HTMLElement?document.activeElement:null);setServicesOpen(true)},
    restoreDialogFocus:(kind:'details'|'services',event:Event)=>{event.preventDefault();requestAnimationFrame(()=>{const opener=openers.current[kind];(opener?.isConnected&&opener.getClientRects().length&&!opener.matches(':disabled')?opener:document.querySelector<HTMLElement>(kind==='details'?'[data-diag-details-trigger]':'[data-diag-services-trigger]'))?.focus()})}}
}
export type DiagnosticsController=ReturnType<typeof useDiagnostics>
