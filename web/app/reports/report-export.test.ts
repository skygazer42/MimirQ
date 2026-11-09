import { describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { exportReportBlobFile, reportExportParams } from './report-export'

vi.mock('sonner',()=>({toast:{error:vi.fn()}}))
vi.mock('@/lib/client-logging',()=>({reportClientError:vi.fn()}))
describe('report export recovery',()=>{
  it('reads JSON blob errors while releasing the pending state and retaining the error object',async()=>{
    const data=new Blob([JSON.stringify({detail:'导出服务暂不可用'})],{type:'application/json'})
    const failure={response:{status:503,data},message:'Request failed with status code 503'}
    const loading=vi.fn()
    await exportReportBlobFile({datasetId:'dataset',datasetName:'报告',pipelineHash:'pipeline',connectorRunsLimit:20,redact:false,setLoading:loading,getBlob:async()=>{throw failure},filenameStem:'report',extension:'html',errorFallback:'导出失败'})
    expect(toast.error).toHaveBeenCalledWith('导出服务暂不可用')
    expect(loading.mock.calls).toEqual([[true],[false]])
    expect(failure.response.data).toBe(data)
  })
  it('keeps raw JSON exports free of the redaction parameter',()=>{
    expect(reportExportParams('',20)).toEqual({connector_runs_limit:20})
    expect(reportExportParams(' pipeline ',50,false)).toEqual({pipeline_hash:'pipeline',connector_runs_limit:50,redact:false})
  })
})
