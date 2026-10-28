'use client'

import { useEffect, useRef } from 'react'

import { Trash2 } from '@/components/icons'
import { SettingsSwitch } from '@/components/settings/settings-switch'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { settingsLayoutTokens } from '@/components/ui/system-page-tokens'
import { cn } from '@/lib/utils'
import type { RuleRow, RuleSection } from '@/components/industry-rules/rule-editor-model'
import styles from '../settings.module.css'

const inputClass = cn(settingsLayoutTokens.input, 'border-transparent bg-[var(--settings-value)] placeholder:text-muted-foreground focus-visible:border-input')
type TextField = 'term' | 'words' | 'followup' | 'name' | 'route'
type Field = { key: TextField; label: string; placeholder: string }
const fields: Record<RuleSection, Field[]> = {
  glossary: [
    { key: 'term', label: '术语 / 缩写', placeholder: '如 485' },
    { key: 'words', label: '检索扩展词', placeholder: '如 RS-485，RS-485 通讯线' },
  ],
  patterns: [
    { key: 'words', label: '触发词', placeholder: '如 报警，通信异常' },
    { key: 'followup', label: '澄清话术', placeholder: '如 请提供设备型号与报警码' },
  ],
  intents: [
    { key: 'name', label: '意图名称', placeholder: '如 故障诊断' },
    { key: 'words', label: '关键词', placeholder: '如 故障，排查' },
    { key: 'route', label: '路由', placeholder: 'default' },
  ],
}

export function RuleRowsEditor({ section, rows, filter, focusRowId, onChange, onRemove }: Readonly<{
  section: RuleSection
  rows: RuleRow[]
  filter: string
  focusRowId: string | null
  onChange: (id: string, patch: Partial<RuleRow>) => void
  onRemove: (id: string) => void
}>) {
  const root = useRef<HTMLDivElement>(null)
  const needle = filter.trim().toLocaleLowerCase()
  const visibleRows = rows.filter(row => fields[section].some(field => row[field.key].toLocaleLowerCase().includes(needle)))

  useEffect(() => {
    if (focusRowId) root.current?.querySelector<HTMLInputElement>(`[data-row-id="${focusRowId}"] input`)?.focus()
  }, [focusRowId])

  return (
    <div ref={root}>
      {visibleRows.length ? (
        <>
          <div className={styles.ruleTableHeader} aria-hidden="true">
            <div className={styles.ruleFields} data-kind={section}>
              {fields[section].map(field => <span key={field.key}>{field.label}</span>)}
              {section === 'patterns' ? <span>启用</span> : null}
            </div>
            <span className="w-10 shrink-0" />
          </div>
          {visibleRows.map(row => {
            const number = rows.indexOf(row) + 1
            const rowName = row.term || row.name || row.words || `第 ${number} 条规则`
            return (
              <div key={row.id} className={styles.ruleEditorRow} data-row-id={row.id} role="group" aria-label={`第 ${number} 条规则`}>
                <div className={styles.ruleFields} data-kind={section}>
                  {fields[section].map(field => {
                    const id = `industry-${section}-${row.id}-${field.key}`
                    return (
                      <div key={field.key} className="min-w-0">
                        <label htmlFor={id} className="mb-2 block text-[13px] font-medium sm:sr-only">{field.label}</label>
                        <Input id={id} value={row[field.key]} placeholder={field.placeholder} className={inputClass} onChange={event => onChange(row.id, { [field.key]: event.target.value })} />
                      </div>
                    )
                  })}
                  {section === 'patterns' ? (
                    <div className="flex min-h-11 items-center justify-between gap-3 sm:min-h-10 sm:justify-end">
                      <label htmlFor={`industry-enabled-${row.id}`} className="text-[13px] font-medium sm:sr-only">启用规则 {number}</label>
                      <SettingsSwitch id={`industry-enabled-${row.id}`} checked={row.enabled} onCheckedChange={enabled => onChange(row.id, { enabled })} />
                    </div>
                  ) : null}
                  {section !== 'glossary' && row.source && !Array.isArray(row.source) && !['name', 'markers', 'keywords', 'followup', 'followup_template'].some(key => Object.hasOwn(row.source!, key)) ? (
                    <p className="text-[13px] leading-6 text-muted-foreground sm:col-span-full">自定义规则，可在 JSON 编辑中修改。</p>
                  ) : null}
                </div>
                <Button type="button" variant="ghost" className="mt-7 size-11 shrink-0 p-0 text-muted-foreground hover:text-destructive sm:mt-0 sm:size-10" aria-label={`移除 ${rowName}`} title="移除规则" onClick={() => onRemove(row.id)}>
                  <Trash2 className="size-4" />
                </Button>
              </div>
            )
          })}
        </>
      ) : (
        <p className="py-10 text-center text-[14px] leading-6 text-muted-foreground">
          {needle ? '没有找到符合条件的规则。' : section === 'glossary' ? '还没有术语，点击「新增术语」开始。' : section === 'patterns' ? '还没有匹配规则，点击「新增规则」开始。' : '还没有意图规则，点击「新增意图」开始。'}
        </p>
      )}
    </div>
  )
}
