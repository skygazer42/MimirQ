'use client'

import { useState } from 'react'
import { Calendar, ChevronDown, Filter, X } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select'
import { FILTER_LABELS, QUICK_ACTIONS, actionName, emptyFilters, isoDateTime, localDateTime, periodLabel, resourceTypeName, validateFilters, type AuditFilters } from './audit-model'
import type { AuditController } from './use-audit'
import styles from './audit.module.css'

export function AuditFiltersBar({ controller: c }: { controller: AuditController }) {
  const [moreOpen, setMoreOpen] = useState(false), [timeOpen, setTimeOpen] = useState(false)
  const [draft, setDraft] = useState<AuditFilters>(emptyFilters), [error, setError] = useState('')
  const [period, setPeriod] = useState({ since: '', until: '' }), [timeError, setTimeError] = useState('')
  const extras = (['resource_id', 'request_id'] as const).filter(key => c.scope.filters[key])
  const any = Object.values(c.filters).length > 0, blocked = Boolean(c.busy)
  function choosePeriod(hours: number | null) {
    const end = new Date()
    c.setFilters({ ...c.scope.filters, since: hours === null ? '' : new Date(end.getTime() - hours * 3_600_000).toISOString(), until: hours === null ? '' : end.toISOString() }); setTimeOpen(false)
  }
  function applyPeriod(event: React.FormEvent) {
    event.preventDefault()
    const next = { ...c.scope.filters, since: isoDateTime(period.since), until: isoDateTime(period.until) }, message = validateFilters(next)
    if (message) { setTimeError(message); return }
    c.setFilters(next); setTimeOpen(false)
  }
  function applyMore(event: React.FormEvent) {
    event.preventDefault()
    const message = validateFilters(draft)
    if (message) { setError(message); return }
    c.setFilters(draft); setMoreOpen(false)
  }
  return <>
    <div className={styles.filters}>
      <span className={styles.filterLabel}>筛选</span>
      <Popover open={timeOpen} onOpenChange={open => { setTimeOpen(open); if (open) { setPeriod({ since: localDateTime(c.scope.filters.since), until: localDateTime(c.scope.filters.until) }); setTimeError('') } }}>
        <PopoverTrigger asChild><Button variant="outline" className={styles.dateTrigger} aria-label="审计时间范围" disabled={blocked}><Calendar /><span>{periodLabel(c.scope.filters)}</span><ChevronDown /></Button></PopoverTrigger>
        <PopoverContent align="start" className={styles.timePopover}>
          <div className={styles.periodPresets}><Button variant="ghost" onClick={() => choosePeriod(null)}>全部时间</Button><Button variant="ghost" onClick={() => choosePeriod(24)}>近 24 小时</Button><Button variant="ghost" onClick={() => choosePeriod(168)}>近 7 天</Button><Button variant="ghost" onClick={() => choosePeriod(720)}>近 30 天</Button></div>
          <form onSubmit={applyPeriod}><Label htmlFor="audit-since">开始时间</Label><Input id="audit-since" type="datetime-local" value={period.since} onChange={event => setPeriod({ ...period, since: event.target.value })} /><Label htmlFor="audit-until">结束时间</Label><Input id="audit-until" type="datetime-local" value={period.until} onChange={event => setPeriod({ ...period, until: event.target.value })} />{timeError ? <p className={styles.fieldError} role="alert">{timeError}</p> : null}<Button type="submit">应用时间</Button></form>
        </PopoverContent>
      </Popover>
      <FilterSelect label="动作" value={c.scope.filters.action} options={c.optionValues.action} all="全部动作" format={actionName} disabled={blocked} onChange={action => c.setFilters({ ...c.scope.filters, action })} />
      <FilterSelect label="操作者" value={c.scope.filters.actor_id} options={c.optionValues.actor_id} all="全部操作者" disabled={blocked} onChange={actor_id => c.setFilters({ ...c.scope.filters, actor_id })} />
      <FilterSelect label="资源类型" value={c.scope.filters.resource_type} options={c.optionValues.resource_type} all="全部资源类型" format={resourceTypeName} disabled={blocked} onChange={resource_type => c.setFilters({ ...c.scope.filters, resource_type })} />
      <span className={styles.spacer} />
      <Dialog open={moreOpen} onOpenChange={setMoreOpen}>
        <Button variant="ghost" className={styles.moreFilters} aria-label="更多审计筛选" disabled={blocked} onClick={() => { setDraft({ ...c.scope.filters }); setError(''); setMoreOpen(true) }}><Filter /><span>更多筛选{extras.length ? ` ${extras.length}` : ''}</span></Button>
        <DialogContent className={styles.filterDialog} onCloseAutoFocus={event => { event.preventDefault(); document.querySelector<HTMLElement>('[aria-label="更多审计筛选"]')?.focus() }}>
          <form className={styles.dialogForm} onSubmit={applyMore}>
            <div className={styles.dialogHeader}><DialogTitle>精确筛选</DialogTitle><DialogDescription>按动作代码、操作者、资源或请求的完整值匹配。</DialogDescription></div>
            <div className={styles.dialogBody}><div className={styles.filterFields}>{(['action', 'actor_id', 'resource_type', 'resource_id', 'request_id'] as const).map(key => <div key={key}><Label htmlFor={`audit-exact-${key}`}>{FILTER_LABELS[key]}</Label><Input id={`audit-exact-${key}`} value={draft[key]} autoComplete="off" maxLength={key === 'action' || key === 'request_id' ? 128 : key === 'resource_type' ? 64 : 255} onChange={event => setDraft({ ...draft, [key]: event.target.value })} /></div>)}</div>{error ? <p className={styles.fieldError} role="alert">{error}</p> : null}</div>
            <div className={styles.dialogFooter}><Button type="button" variant="outline" onClick={() => setMoreOpen(false)}>取消</Button><Button type="submit">应用筛选</Button></div>
          </form>
        </DialogContent>
      </Dialog>
      {any ? <Button variant="ghost" size="icon" aria-label="清空审计筛选" disabled={blocked} onClick={() => c.setFilters(emptyFilters())}><X /></Button> : null}<span className={styles.tenantLabel}>当前租户</span>
    </div>
    <div className={styles.presets}><span>快捷筛选</span>{QUICK_ACTIONS.map(action => <button key={action.value} type="button" aria-pressed={c.scope.filters.action === action.value} disabled={blocked} onClick={() => c.setFilters({ ...c.scope.filters, action: c.scope.filters.action === action.value ? '' : action.value })}>{action.label}</button>)}
      {extras.length ? <span className={styles.applied}>{extras.map(key => <button key={key} disabled={blocked} title={c.scope.filters[key]} aria-label={`移除${FILTER_LABELS[key]}筛选`} onClick={() => c.setFilters({ ...c.scope.filters, [key]: '' })}>{FILTER_LABELS[key]} · {c.scope.filters[key]}<X /></button>)}</span> : null}
    </div>
  </>
}

function FilterSelect({ label, value, options, all, format = value => value, disabled, onChange }: { label: string; value: string; options: string[]; all: string; format?: (value: string) => string; disabled: boolean; onChange: (value: string) => void }) {
  return <Select value={value ? `value:${value}` : 'all'} onValueChange={next => onChange(next === 'all' ? '' : next.slice(6))} disabled={disabled}>
    <SelectTrigger aria-label={label} className={styles.filterTrigger}><span title={value ? format(value) : all}>{value ? format(value) : all}</span></SelectTrigger>
    <SelectContent className={styles.filterOptions}><SelectItem value="all">{all}</SelectItem>{options.map(option => <SelectItem key={option} value={`value:${option}`}><span className={styles.optionText}><strong>{format(option)}</strong>{format(option) !== option ? <small>{option}</small> : null}</span></SelectItem>)}</SelectContent>
  </Select>
}
