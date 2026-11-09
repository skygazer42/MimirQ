import { describe, expect, it } from 'vitest'
import { recordedRiskValue, reportAuditRows, reportCoverage, reportStatusRows } from './report-overview-model'
import { filterReportFindings } from './report-format'

describe('report overview values',()=>{
  it('keeps every actual status and does not infer success from missing statistics',()=>{
    expect(reportStatusRows({})).toEqual([])
    expect(reportStatusRows({completed:118,parsing:6,failed:3,quarantined:1}).reduce((sum,row)=>sum+row.value,0)).toBe(128)
    expect(reportStatusRows({archived:3,failed:0,invalid:NaN})).toEqual([{key:'archived',value:3,label:'archived',tone:'info'}])
  })
  it('distinguishes unavailable coverage from a true zero',()=>{
    expect(reportCoverage(0,0)).toBe('—')
    expect(reportCoverage(0,128)).toBe('0.0%')
    expect(reportCoverage(122,128)).toBe('95.3%')
    expect(reportCoverage(140,128)).toBe('100.0%')
  })
  it('reads observed gate metrics without introducing an assumed threshold',()=>{
    const rows=reportAuditRows({status:'failed',plugin_refs:[],plugin_package_hashes:[],failure_categories:{},gates:[{name:'实际门禁',status:'failed',metrics:{hit_at_1:.88,retrieval_noise_rate:0},failed_conditions:['hit_at_1 < 0.90']}]})
    expect(rows).toEqual([{key:'实际门禁:hit_at_1',label:'召回命中 Hit@1',value:'88.0%',gate:'实际门禁',status:'failed'},{key:'实际门禁:retrieval_noise_rate',label:'噪声占比',value:'0.0%',gate:'实际门禁',status:'failed'}])
    expect(reportAuditRows(null)).toEqual([])
  })
  it('keeps an MRR-only gate visible and preserves its decimal scale',()=>{
    expect(reportAuditRows({status:'passed',plugin_refs:[],plugin_package_hashes:[],failure_categories:{},gates:[{name:'排序门禁',status:'passed',metrics:{retrieval_mrr:.62,retrieval_ndcg:.71},failed_conditions:[]}]}).map(row=>row.value)).toEqual(['0.620','0.710'])
  })
  it('filters only positive warning/error hits and keeps unrecorded risks distinct from zero',()=>{
    expect(filterReportFindings([{key:'zero',label:'未命中',severity:'warning',count:0},{key:'info',label:'正常统计',severity:'info',count:7},{key:'risk',label:'风险',severity:'error',count:2}],true).map(row=>row.key)).toEqual(['risk'])
    expect(recordedRiskValue(0,false)).toBe('待评估')
    expect(recordedRiskValue(0,true)).toBe('0')
    expect(recordedRiskValue(3,false)).toBe('3')
  })
})
