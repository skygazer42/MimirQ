'use client'

import { useState, type FormEvent } from 'react'
import { Calendar, ChevronDown, Filter, X } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select'
import type { AuditLogFilters } from '@/types/audit'
import {
  FILTER_LABELS,
  FILTER_KEYS,
  FILTER_MAX_LENGTH,
  QUICK_ACTIONS,
  getAuditActionLabel,
  createAuditFilterDraft,
  parseAuditLocalDateTime,
  formatAuditLocalDateTime,
  formatAuditPeriod,
  getAuditResourceTypeLabel,
  getAuditFilterError,
  type AuditFilters,
} from './audit-model'
import { AUDIT_SUGGESTION_LIMIT, type AuditState } from './use-audit'
import styles from './audit.module.css'

const FILTER_VALUE_PREFIX = 'value:'

function getTextFilterDraft(filters: AuditFilters) {
  return {
    actor_id: filters.actor_id,
    action: filters.action,
    resource_type: filters.resource_type,
    resource_id: filters.resource_id,
    request_id: filters.request_id,
  }
}

export function AuditFiltersBar({ audit }: Readonly<{ audit: AuditState }>) {
  const [moreOpen, setMoreOpen] = useState(false)
  const [timeOpen, setTimeOpen] = useState(false)
  const [draft, setDraft] = useState(() => getTextFilterDraft(audit.scope.filters))
  const [error, setError] = useState<string | undefined>()
  const [period, setPeriod] = useState<Partial<Pick<AuditFilters, 'since' | 'until'>>>({})
  const [timeError, setTimeError] = useState<string | undefined>()
  const extras = (['resource_id', 'request_id'] as const).filter((key) => audit.scope.filters[key].length > 0)
  const hasFilters = Object.keys(audit.filters).length > 0
  const blocked = audit.busy !== null
  function choosePeriod(hours: number | null) {
    if (hours === null) audit.setFilters((current) => ({ ...current, since: '', until: '' }))
    else {
      const end = new Date()
      audit.setFilters((current) => ({
        ...current,
        since: new Date(end.getTime() - hours * 3_600_000).toISOString(),
        until: end.toISOString(),
      }))
    }
    setTimeOpen(false)
  }
  function applyPeriod(event: FormEvent) {
    event.preventDefault()
    const nextPeriod = {
      since: period.since ?? audit.scope.filters.since,
      until: period.until ?? audit.scope.filters.until,
    }
    const message = getAuditFilterError(nextPeriod)
    if (message !== undefined) {
      setTimeError(message)
      return
    }
    audit.setFilters((current) => ({
      ...current,
      since: period.since === undefined ? nextPeriod.since : parseAuditLocalDateTime(nextPeriod.since),
      until: period.until === undefined ? nextPeriod.until : parseAuditLocalDateTime(nextPeriod.until),
    }))
    setTimeOpen(false)
  }
  function applyMore(event: FormEvent) {
    event.preventDefault()
    const message = getAuditFilterError(draft)
    if (message !== undefined) {
      setError(message)
      return
    }
    audit.setFilters((current) => ({ ...current, ...draft }))
    setMoreOpen(false)
  }
  return (
    <>
      <div className={styles.filters}>
        <span className={styles.filterLabel}>筛选</span>
        <Popover
          open={timeOpen}
          onOpenChange={(open) => {
            setTimeOpen(open)
            if (open) {
              setPeriod({})
              setTimeError(undefined)
            }
          }}
        >
          <PopoverTrigger asChild>
            <Button variant="outline" className={styles.dateTrigger} aria-label="审计时间范围" disabled={blocked}>
              <Calendar />
              <span>{formatAuditPeriod(audit.scope.filters)}</span>
              <ChevronDown />
            </Button>
          </PopoverTrigger>
          <PopoverContent align="start" className={styles.timePopover}>
            <div className={styles.periodPresets}>
              <Button variant="ghost" onClick={() => choosePeriod(null)}>
                全部时间
              </Button>
              <Button variant="ghost" onClick={() => choosePeriod(24)}>
                近 24 小时
              </Button>
              <Button variant="ghost" onClick={() => choosePeriod(168)}>
                近 7 天
              </Button>
              <Button variant="ghost" onClick={() => choosePeriod(720)}>
                近 30 天
              </Button>
            </div>
            <form onSubmit={applyPeriod}>
              <Label htmlFor="audit-since">开始时间</Label>
              <Input
                id="audit-since"
                type="datetime-local"
                step="any"
                value={period.since ?? formatAuditLocalDateTime(audit.scope.filters.since)}
                onChange={(event) => setPeriod({ ...period, since: event.currentTarget.value })}
              />
              <Label htmlFor="audit-until">结束时间</Label>
              <Input
                id="audit-until"
                type="datetime-local"
                step="any"
                value={period.until ?? formatAuditLocalDateTime(audit.scope.filters.until)}
                onChange={(event) => setPeriod({ ...period, until: event.currentTarget.value })}
              />
              {timeError !== undefined ? (
                <p className={styles.fieldError} role="alert">
                  {timeError}
                </p>
              ) : null}
              <Button type="submit">应用时间</Button>
            </form>
          </PopoverContent>
        </Popover>
        <FilterSelect
          label="动作"
          value={audit.scope.filters.action}
          options={audit.filterSuggestions.action}
          allLabel="全部动作"
          format={getAuditActionLabel}
          disabled={blocked}
          onChange={(action) => audit.setFilters((current) => ({ ...current, action }))}
        />
        <FilterSelect
          label="操作者"
          value={audit.scope.filters.actor_id}
          options={audit.filterSuggestions.actor_id}
          allLabel="全部操作者"
          disabled={blocked}
          onChange={(actor_id) => audit.setFilters((current) => ({ ...current, actor_id }))}
        />
        <FilterSelect
          label="资源类型"
          value={audit.scope.filters.resource_type}
          options={audit.filterSuggestions.resource_type}
          allLabel="全部资源类型"
          format={getAuditResourceTypeLabel}
          disabled={blocked}
          onChange={(resource_type) => audit.setFilters((current) => ({ ...current, resource_type }))}
        />
        <span className={styles.spacer} />
        <Dialog
          open={moreOpen}
          onOpenChange={(open) => {
            setMoreOpen(open)
            if (open) {
              setDraft(getTextFilterDraft(audit.scope.filters))
              setError(undefined)
            }
          }}
        >
          <DialogTrigger asChild>
            <Button variant="ghost" className={styles.moreFilters} aria-label="更多审计筛选" disabled={blocked}>
              <Filter />
              <span>更多筛选{extras.length ? ` ${extras.length}` : ''}</span>
            </Button>
          </DialogTrigger>
          <DialogContent className={styles.filterDialog}>
            <form className={styles.dialogForm} onSubmit={applyMore}>
              <div className={styles.dialogHeader}>
                <DialogTitle>精确筛选</DialogTitle>
                <DialogDescription>按动作代码、操作者、资源或请求的完整值匹配。</DialogDescription>
              </div>
              <div className={styles.dialogBody}>
                <div className={styles.filterFields}>
                  {(['action', 'actor_id', 'resource_type', 'resource_id', 'request_id'] as const).map((key) => (
                    <div key={key}>
                      <Label htmlFor={`audit-exact-${key}`}>{FILTER_LABELS[key]}</Label>
                      <Input
                        id={`audit-exact-${key}`}
                        value={draft[key]}
                        autoComplete="off"
                        maxLength={FILTER_MAX_LENGTH[key]}
                        onChange={(event) => setDraft({ ...draft, [key]: event.target.value })}
                      />
                    </div>
                  ))}
                </div>
                {error !== undefined ? (
                  <p className={styles.fieldError} role="alert">
                    {error}
                  </p>
                ) : null}
              </div>
              <div className={styles.dialogFooter}>
                <Button type="button" variant="outline" onClick={() => setMoreOpen(false)}>
                  取消
                </Button>
                <Button type="submit">应用筛选</Button>
              </div>
            </form>
          </DialogContent>
        </Dialog>
        {hasFilters ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label="清空审计筛选"
            disabled={blocked}
            onClick={() => audit.setFilters(createAuditFilterDraft())}
          >
            <X />
          </Button>
        ) : null}
        <span className={styles.tenantLabel}>当前租户</span>
      </div>
      <div className={styles.presets}>
        <span>建议来自最近 {AUDIT_SUGGESTION_LIMIT.toLocaleString('zh-CN')} 条及当前页，其他值可用精确筛选。</span>
        <span>快捷筛选</span>
        {QUICK_ACTIONS.map((action) => (
          <button
            key={action.value}
            type="button"
            aria-pressed={audit.scope.filters.action === action.value}
            disabled={blocked}
            onClick={() =>
              audit.setFilters((current) => ({
                ...current,
                action: current.action === action.value ? '' : action.value,
              }))
            }
          >
            {action.label}
          </button>
        ))}
        {extras.length ? (
          <span className={styles.applied}>
            {extras.map((key) => (
              <button
                key={key}
                disabled={blocked}
                title={audit.scope.filters[key]}
                aria-label={`移除${FILTER_LABELS[key]}筛选`}
                onClick={() => audit.setFilters((current) => ({ ...current, [key]: '' }))}
              >
                {FILTER_LABELS[key]} · {audit.scope.filters[key]}
                <X />
              </button>
            ))}
          </span>
        ) : null}
      </div>
    </>
  )
}

export function AuditFilterSnapshot({ applied }: Readonly<{ applied: AuditLogFilters }>) {
  return FILTER_KEYS.some((key) => applied[key] !== undefined) ? (
    <dl className={styles.scopeSnapshot}>
      {FILTER_KEYS.map((key) => {
        const value = applied[key]
        return value === undefined ? null : (
          <div key={key}>
            <dt>{FILTER_LABELS[key]}</dt>
            <dd>{value}</dd>
          </div>
        )
      })}
    </dl>
  ) : (
    <p className={styles.allScope}>当前租户 · 全部日志</p>
  )
}

function FilterSelect({
  label,
  value,
  options,
  allLabel,
  format = (value) => value,
  disabled,
  onChange,
}: {
  label: string
  value: string
  options: string[]
  allLabel: string
  format?: (value: string) => string
  disabled: boolean
  onChange: (value: string) => void
}) {
  const selectedLabel = value === '' ? allLabel : format(value)
  return (
    <Select
      value={value === '' ? 'all' : `${FILTER_VALUE_PREFIX}${value}`}
      onValueChange={(next) => onChange(next === 'all' ? '' : next.slice(FILTER_VALUE_PREFIX.length))}
      disabled={disabled}
    >
      <SelectTrigger aria-label={label} className={styles.filterTrigger}>
        <span title={selectedLabel}>{selectedLabel}</span>
      </SelectTrigger>
      <SelectContent className={styles.filterOptions}>
        <SelectItem value="all">{allLabel}</SelectItem>
        {options.map((option) => {
          const optionLabel = format(option)
          return (
            <SelectItem key={option} value={`${FILTER_VALUE_PREFIX}${option}`}>
              <span className={styles.optionText}>
                <strong>{optionLabel}</strong>
                {optionLabel !== option ? <small>{option}</small> : null}
              </span>
            </SelectItem>
          )
        })}
      </SelectContent>
    </Select>
  )
}
