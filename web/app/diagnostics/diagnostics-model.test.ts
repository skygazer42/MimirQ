import { describe,expect,it } from 'vitest'
import { buildChannels, dependencyState, driftVerdict, metricRows, perfVerdict, readNumber, rerankState } from './diagnostics-model'

describe('diagnostic evidence semantics',()=>{
  it('keeps missing, blank and zero values distinct',()=>{
    expect(readNumber('')).toBeNull();expect(readNumber('  ')).toBeNull();expect(readNumber(false)).toBeNull();expect(readNumber('0')).toBe(0)
    const empty=metricRows(null)
    expect(empty.find(m=>m.key==='citations')?.value).toBe('待执行')
    const missing=metricRows({query_for_retrieval:'x',prompt_text:'',prompt_messages:[],variables:{},metrics:{}})
    expect(missing.find(m=>m.key==='citations')?.value).toBe('未返回')
    const zeros=metricRows({query_for_retrieval:'x',prompt_text:'',prompt_messages:[],variables:{},citations:[],metrics:{prompt_tokens:0,elapsed_sec:0}})
    expect(zeros.find(m=>m.key==='citations')?.raw).toBe(0)
    expect(zeros.find(m=>m.key==='latency')?.raw).toBe(0)
    expect(zeros.find(m=>m.key==='generation')?.value).toBe('未返回')
  })
  it('preserves extra channels and a returned zero count',()=>{
    const channels=buildChannels({channels:{vector:{candidate_count:32},lexical:{candidate_count:28},graph:{candidate_count:0},custom:{returned_count:4}}})
    expect(channels.map(c=>c.count)).toEqual([32,28,0,4])
    expect(channels.find(c=>c.key==='graph')?.label).toBe('图谱召回')
  })
  it('reads the backend channels.counts envelope without turning metadata into channels',()=>{
    const channels=buildChannels({channels:{timing:{vector_elapsed_sec:.15},counts:{vector_candidates:32,bm25_candidates:28,sparse_candidates:0},retrieval_degraded:false,retrieval_degraded_reasons:[]}})
    expect(channels.map(c=>c.count)).toEqual([32,28,0])
    expect(channels.map(c=>c.key)).toEqual(['vector_candidates','bm25_candidates','sparse_candidates'])
  })
  it('does not treat reranker configuration as proof of execution',()=>{
    expect(rerankState({}, {enable_reranker:true}).label).toBe('已启用')
    expect(rerankState({rerank:{used:false}}, {enable_reranker:true}).label).toBe('未执行')
    expect(rerankState({rerank:{used:true}}, {}).label).toBe('已执行')
    expect(rerankState({}, {}).label).toBe('未返回')
  })
  it('honors disabled runtime dependencies and preserves unknown states',()=>{
    expect(dependencyState({enabled:false,status:'disabled'},{status:'error'}).label).toBe('未启用')
    expect(dependencyState(undefined).label).toBe('未知')
    expect(dependencyState({status:'error'}).tone).toBe('danger')
    expect(dependencyState({backend:'memory',status:'disabled',required:false}).label).toBe('内存模式')
  })
  it('does not call no samples or an unsupported backend a zero-drift pass',()=>{
    expect(driftVerdict({ok:true,drift:{n:0},above_threshold:{count:0,ratio:0}}).label).toBe('无可比样本')
    expect(driftVerdict({ok:false,error:'unsupported_vector_backend',vector_backend:'memory'}).label).toBe('后端不支持')
    expect(driftVerdict({ok:true,drift:{n:100},above_threshold:{count:12,ratio:.12}}).ratio).toBe(.12)
  })
  it('reads canonical drift count/avg and keeps zero comparable samples unknown',()=>{
    expect(driftVerdict({ok:true,drift:{count:200,avg:.025},above_threshold:{count:24,ratio:.12}})).toMatchObject({samples:200,average:.025,ratio:.12})
    expect(driftVerdict({ok:true,drift:{count:0,avg:null},above_threshold:{count:0,ratio:0}}).label).toBe('无可比样本')
  })
  it('uses the nested performance gate decision instead of HTTP success',()=>{
    expect(perfVerdict({current_report:{cases:[]},diff:{strict_gate:{passed:false},ok:true}}).label).toBe('未通过')
    expect(perfVerdict({current_report:{cases:[]},diff:{ok:false}}).label).toBe('未通过')
    expect(perfVerdict({current_report:{cases:[]},diff:{ok:true}}).label).toBe('通过')
    expect(perfVerdict({current_report:{cases:[]}}).label).toBe('结论未返回')
  })
})
