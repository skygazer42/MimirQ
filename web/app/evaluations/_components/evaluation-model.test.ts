import { describe, expect, it } from 'vitest'
import type { RagasItem, RagasRunDetail } from '@/lib/api/evaluation'
import { hasLowScore, itemContexts, metricStatistics, numericScore } from './evaluation-model'

function item(scores: RagasItem['scores'] = {}): RagasItem {
  return { id:'sample', run_id:'run', turn_index:1, user_input:'问题', response:'回答', scores, citations:[], created_at:'2026-10-25T10:00:00Z' }
}
function detail(items: RagasItem[], summary: RagasRunDetail['run']['summary'] = {}): RagasRunDetail {
  return {run:{id:'run',status:'completed',metrics:['faithfulness'],params:{},summary,created_at:'2026-10-25T10:00:00Z'},items}
}
describe('evaluation scores and original evidence',()=>{
  it('keeps missing and invalid scores distinct from a real zero',()=>{
    for(const value of [null,undefined,'',false,'0.8',NaN,Infinity]) expect(numericScore(value)).toBeNull()
    expect(numericScore(0)).toBe(0)
    expect(metricStatistics(detail([item({faithfulness:null})]),['faithfulness'])[0]).toMatchObject({mean:null,p50:null,p90:null,passRate:null})
  })
  it('uses any requested metric below 0.80, without marking unscored samples low',()=>{
    expect(hasLowScore(item({faithfulness:.8,response_relevancy:null}),['faithfulness','response_relevancy'])).toBe(false)
    expect(hasLowScore(item({faithfulness:.9,response_relevancy:.79}),['faithfulness','response_relevancy'])).toBe(true)
    expect(hasLowScore(item({faithfulness:0}),['faithfulness'])).toBe(true)
    expect(hasLowScore(item({unrequested:.1}),['faithfulness'])).toBe(false)
  })
  it('uses the server mean when present, and calculates sample statistics from finite values',()=>{
    const result=metricStatistics(detail([item({faithfulness:1}),item({faithfulness:.8}),item({faithfulness:.2}),item({faithfulness:null})],{faithfulness:.67}),['faithfulness'])[0]
    expect(result.mean).toBe(.67)
    expect(result.p50).toBe(.8)
    expect(result.passRate).toBeCloseTo(2/3)
    expect(metricStatistics(detail([item({faithfulness:0}),item({faithfulness:1})]),['faithfulness'])[0].mean).toBe(.5)
  })
  it('reads saved contexts first and only uses actual citation text as a fallback',()=>{
    const sample={...item(),retrieved_contexts:['原始上下文'],citations:[{content:'引用正文',document_id:'document'}]}
    expect(itemContexts(sample)).toEqual(['原始上下文'])
    expect(itemContexts({...sample,retrieved_contexts:[]})).toEqual(['引用正文'])
    expect(itemContexts({...item(),citations:[{document_id:'document',title:'文档名'}]})).toEqual([])
  })
})
