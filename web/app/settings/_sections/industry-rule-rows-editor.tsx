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

const inputClass = cn(
  settingsLayoutTokens.input,
  'border-transparent bg-[var(--settings-value)] placeholder:text-muted-foreground focus-visible:border-input',
)
type TextField = 'term' | 'words' | 'followup' | 'name' | 'route'
type RuleField = { key: TextField; label: string; placeholder: string }

const RULE_FIELDS: Readonly<Record<RuleSection, readonly RuleField[]>> = {
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

const EMPTY_RULE_MESSAGES: Readonly<Record<RuleSection, string>> = {
  glossary: '还没有术语，点击「新增术语」开始。',
  patterns: '还没有匹配规则，点击「新增规则」开始。',
  intents: '还没有意图规则，点击「新增意图」开始。',
}

export function RuleRowsEditor({
  section,
  rows,
  filter,
  focusTarget,
  onChange,
  onRemove,
}: Readonly<{
  section: RuleSection
  rows: readonly RuleRow[]
  filter: string
  focusTarget: Readonly<{ rowId: string }> | null
  onChange: (id: string, patch: Partial<RuleRow>) => void
  onRemove: (row: RuleRow, index: number, nextVisibleRowId: string | null) => void
}>) {
  const root = useRef<HTMLDivElement>(null)
  const searchText = filter.trim().toLocaleLowerCase()
  const sectionFields = RULE_FIELDS[section]
  const isPatternSection = section === 'patterns'
  const visibleRows = rows.flatMap((row, index) =>
    searchText === '' || sectionFields.some((field) => row[field.key].toLocaleLowerCase().includes(searchText))
      ? [{ row, index }]
      : [],
  )

  useEffect(() => {
    if (focusTarget === null) return
    root.current?.querySelector<HTMLInputElement>(`[data-row-id="${focusTarget.rowId}"] input`)?.focus()
  }, [focusTarget])

  return (
    <div ref={root}>
      {visibleRows.length > 0 ? (
        <>
          <div className={styles.ruleTableHeader} aria-hidden="true">
            <div className={styles.ruleFields} data-kind={section}>
              {sectionFields.map((field) => (
                <span key={field.key}>{field.label}</span>
              ))}
              {isPatternSection ? <span>启用</span> : null}
            </div>
            <span className="w-10 shrink-0" />
          </div>
          {visibleRows.map(({ row, index }, visibleIndex) => {
            const number = index + 1
            const rowName = row[sectionFields[0].key]
            const source = row.source
            const isCustomRule =
              section !== 'glossary' &&
              source !== null &&
              !Array.isArray(source) &&
              !['name', 'markers', 'keywords', 'followup', 'followup_template'].some((key) =>
                Object.hasOwn(source, key),
              )
            return (
              <div
                key={row.id}
                className={styles.ruleEditorRow}
                data-row-id={row.id}
                role="group"
                aria-label={`第 ${number} 条规则`}
              >
                <div className={styles.ruleFields} data-kind={section}>
                  {sectionFields.map((field) => {
                    const id = `industry-${section}-${row.id}-${field.key}`
                    return (
                      <div key={field.key} className="min-w-0">
                        <label htmlFor={id} className="mb-2 block text-[13px] font-medium sm:sr-only">
                          {field.label}
                        </label>
                        <Input
                          id={id}
                          value={row[field.key]}
                          placeholder={field.placeholder}
                          className={inputClass}
                          onChange={(event) => onChange(row.id, { [field.key]: event.currentTarget.value })}
                        />
                      </div>
                    )
                  })}
                  {isPatternSection ? (
                    <div className="flex min-h-11 items-center justify-between gap-3 sm:min-h-10 sm:justify-end">
                      <label htmlFor={`industry-enabled-${row.id}`} className="text-[13px] font-medium sm:sr-only">
                        启用规则 {number}
                      </label>
                      <SettingsSwitch
                        id={`industry-enabled-${row.id}`}
                        checked={row.enabled}
                        onCheckedChange={(enabled) => onChange(row.id, { enabled })}
                      />
                    </div>
                  ) : null}
                  {isCustomRule ? (
                    <p className="text-[13px] leading-6 text-muted-foreground sm:col-span-full">
                      自定义规则，可在 JSON 编辑中修改。
                    </p>
                  ) : null}
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  className="mt-7 size-11 shrink-0 p-0 text-muted-foreground hover:text-destructive sm:mt-0 sm:size-10"
                  aria-label={rowName === '' ? `移除第 ${number} 条规则` : `移除 ${rowName}`}
                  title="移除规则"
                  onClick={() => {
                    const next = visibleRows[visibleIndex + 1] ?? visibleRows[visibleIndex - 1]
                    onRemove(row, index, next?.row.id ?? null)
                  }}
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            )
          })}
        </>
      ) : (
        <p className="py-10 text-center text-[14px] leading-6 text-muted-foreground">
          {searchText === '' ? EMPTY_RULE_MESSAGES[section] : '没有找到符合条件的规则。'}
        </p>
      )}
    </div>
  )
}
