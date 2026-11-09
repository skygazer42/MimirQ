'use client'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Loader2,Play } from '@/components/icons'
import { driftVerdict,numeric,performanceRows,perfVerdict,record,timestamp } from './diagnostics-model'
import { Status } from './diagnostics-controls'
import type { DiagnosticsController } from './use-diagnostics'
import styles from './diagnostics.module.css'

export function DriftProbe({controller:c}:{controller:DiagnosticsController}) {
  const result=c.drift.result,verdict=driftVerdict(result?.data)
  return <section className={styles.probeSection} aria-label="向量漂移检查">
    <div className={styles.sectionHeading}><h2>向量漂移</h2><span className={styles.sectionSubtitle}>比较所选数据集的活动分块样本</span><span className={styles.spacer}/><Status {...(c.drift.status==='running'?{label:'检查中',tone:'info'}:c.drift.status==='error'?{label:'请求失败',tone:'danger'}:verdict)}/></div>
    <form className={styles.probeForm} noValidate onSubmit={event=>{event.preventDefault();void c.runDrift()}}>
      <div><Label htmlFor="drift-samples">采样数量</Label><Input id="drift-samples" type="number" min={1} max={2000} step={1} disabled={c.drift.status==='running'} value={c.driftParams.first} aria-invalid={Boolean(c.driftErrors.first)} aria-describedby={c.driftErrors.first?'drift-samples-error':undefined} onChange={event=>c.changeDriftParams({...c.driftParams,first:event.target.value})}/>{c.driftErrors.first?<p id="drift-samples-error" className={styles.fieldError} role="alert">{c.driftErrors.first}</p>:null}</div>
      <div><Label htmlFor="drift-threshold">距离阈值</Label><Input id="drift-threshold" type="number" min={0} max={1} step={.01} disabled={c.drift.status==='running'} value={c.driftParams.second} aria-invalid={Boolean(c.driftErrors.second)} aria-describedby={c.driftErrors.second?'drift-threshold-error':undefined} onChange={event=>c.changeDriftParams({...c.driftParams,second:event.target.value})}/>{c.driftErrors.second?<p id="drift-threshold-error" className={styles.fieldError} role="alert">{c.driftErrors.second}</p>:null}</div>
      <Button type="submit" className={styles.primary} disabled={c.drift.status==='running'||!c.canDrift||c.datasetsQuery.isPending||c.missingDataset}>{c.drift.status==='running'?<Loader2 className="animate-spin"/>:<Play/>}{c.drift.status==='running'?'检查中':'运行漂移检查'}</Button>
    </form>
    {!c.canDrift?<p className={styles.probeExplanation}>当前 {c.vectorBackend} 后端不支持此检查。</p>:<p className={styles.probeExplanation}>余弦距离达到阈值的样本计入超阈值数量。</p>}
    {c.drift.error?<p role="alert" className={styles.domainError}>{c.drift.error}</p>:null}
    {result?<>
      <p className={styles.resultScope}>结果范围：{result.scope.datasetName} · 采样上限 {result.params.first} · 阈值 {result.params.second} · 返回于 {timestamp(result.finishedAt)}</p>
      {verdict.error?<p className={styles.domainWarning} role="status">{verdict.error}</p>:null}
      <dl className={styles.probeMetrics}><div><dt>可比样本</dt><dd>{numeric(verdict.samples,0)}</dd></div><div><dt>超阈值样本</dt><dd>{numeric(verdict.above,0)}</dd></div><div><dt>超阈值比例</dt><dd>{verdict.samples&&verdict.ratio!==null?`${numeric(verdict.ratio*100,2)}%`:'未评估'}</dd></div><div><dt>平均距离</dt><dd>{numeric(verdict.average,5)}</dd></div></dl>
      <dl className={styles.additionalFacts}><div><dt>缺失向量</dt><dd>{numeric(typeof result.data.missing_vectors==='number'?result.data.missing_vectors:null,0)}</dd></div><div><dt>维度不一致</dt><dd>{numeric(typeof result.data.dim_mismatch==='number'?result.data.dim_mismatch:null,0)}</dd></div><div><dt>向量后端</dt><dd>{typeof result.data.vector_backend==='string'?result.data.vector_backend:'未返回'}</dd></div></dl>
    </>:<div className={styles.probeEmpty}><h3>{c.drift.status==='running'?'正在比较样本':'尚未运行漂移检查'}</h3><p>运行后查看样本数量、距离分布和超阈值比例。</p></div>}
  </section>
}
export function PerformanceProbe({controller:c}:{controller:DiagnosticsController}) {
  const result=c.perf.result,verdict=perfVerdict(result?.data),rows=performanceRows(result?.data),diff=record(result?.data.diff)
  return <section className={styles.probeSection} aria-label="性能门禁检查">
    <div className={styles.sectionHeading}><h2>性能门禁</h2><span className={styles.sectionSubtitle}>与后端基线及策略比较</span><span className={styles.spacer}/><Status {...(c.perf.status==='running'?{label:'运行中',tone:'info'}:c.perf.status==='error'?{label:'请求失败',tone:'danger'}:verdict)}/></div>
    <form className={styles.probeForm} noValidate onSubmit={event=>{event.preventDefault();void c.runPerf()}}>
      <div><Label htmlFor="perf-iterations">迭代次数</Label><Input id="perf-iterations" type="number" min={1} max={200} step={1} disabled={c.perf.status==='running'} value={c.perfParams.first} aria-invalid={Boolean(c.perfErrors.first)} aria-describedby={c.perfErrors.first?'perf-iterations-error':undefined} onChange={event=>c.changePerfParams({...c.perfParams,first:event.target.value})}/>{c.perfErrors.first?<p id="perf-iterations-error" className={styles.fieldError} role="alert">{c.perfErrors.first}</p>:null}</div>
      <div><Label htmlFor="perf-timeout">超时（秒）</Label><Input id="perf-timeout" type="number" min={.05} max={10} step={.05} disabled={c.perf.status==='running'} value={c.perfParams.second} aria-invalid={Boolean(c.perfErrors.second)} aria-describedby={c.perfErrors.second?'perf-timeout-error':undefined} onChange={event=>c.changePerfParams({...c.perfParams,second:event.target.value})}/>{c.perfErrors.second?<p id="perf-timeout-error" className={styles.fieldError} role="alert">{c.perfErrors.second}</p>:null}</div>
      <Button type="submit" className={styles.primary} disabled={c.perf.status==='running'}>{c.perf.status==='running'?<Loader2 className="animate-spin"/>:<Play/>}{c.perf.status==='running'?'运行中':'运行性能门禁'}</Button>
    </form>
    {c.perf.error?<p role="alert" className={styles.domainError}>{c.perf.error}</p>:null}
    {result?<>
      <p className={styles.resultScope}>全局 API · 每项 {result.params.first} 次 · 超时 {result.params.second} 秒 · 返回于 {timestamp(result.finishedAt)}</p>
      <div className={styles.sectionHeading}><h3>分项结果</h3><Status {...verdict}/></div>
      <p className={styles.tableScrollHint}>左右滚动查看更多指标</p>
      <div className={styles.performanceScroll}><table className={styles.performanceTable} aria-label="性能门禁分项结果"><thead><tr><th>接口</th><th>成功 / 次数</th><th>P50 · ms</th><th>P95 · ms</th><th>P99 · ms</th><th>QPS</th><th>与基线比较</th></tr></thead><tbody>{rows.map(row=><tr key={row.key}><th><strong>{row.name}</strong><small>{row.path}</small></th><td>{numeric(row.okCount,0)} / {numeric(row.iterations,0)}</td><td>{numeric(row.p50)}</td><td>{numeric(row.p95)}</td><td>{numeric(row.p99)}</td><td>{numeric(row.qps)}</td><td><Status label={row.regressed===true?'退化':row.regressed===false?'未退化':'未返回'} tone={row.regressed===true?'warning':'neutral'}/></td></tr>)}</tbody></table></div>
      {!rows.length?<p className={styles.sectionEmpty}>分项数据未返回，可查看原始响应。</p>:null}
      <details className={styles.gateDetails}><summary>门禁比较详情</summary><pre className={styles.rawContent}>{JSON.stringify(diff,null,2)}</pre></details>
    </>:<div className={styles.probeEmpty}><h3>{c.perf.status==='running'?'正在检查接口性能':'尚未运行性能门禁'}</h3><p>运行后按接口查看耗时与基线比较结果。</p></div>}
  </section>
}
