'use client'

import { useEffect, useState } from 'react'
import { Check, ChevronDown, ChevronRight, Search } from '@/components/icons'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { PARSER_BACKEND_OPTIONS, getParserOption } from '@/lib/parser-options'
import { normalizeParserBackendName, resolveParserBackendForFilename } from '@/lib/parser-compat'
import { detachPromise } from '@/lib/utils'
import styles from './parsing-compare.module.css'

type ParsingParserPickerProps = {
  value: string
  filename?: string
  disabled?: boolean
  triggerVariant?: 'compact' | 'row'
  onChange: (backend: string) => void
}

export function ParsingParserPicker({
  value,
  filename,
  disabled,
  triggerVariant = 'compact',
  onChange,
}: Readonly<ParsingParserPickerProps>) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  useEffect(() => {
    if (disabled) setOpen(false)
  }, [disabled])
  const { capabilities, loading, error, refresh, parserBackendAvailable } = usePipelineCapabilities()
  const selected = getParserOption(value)
  const query = search.trim().toLocaleLowerCase()
  const options = PARSER_BACKEND_OPTIONS.filter((option) =>
    `${option.label} ${option.value} ${option.description}`.toLocaleLowerCase().includes(query),
  )

  return (
    <Dialog
      open={open && !disabled}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) setSearch('')
      }}
    >
      <DialogTrigger asChild>
        {triggerVariant === 'row' ? (
          <button
            type="button"
            className={styles.parserRowTrigger}
            disabled={disabled}
            aria-label={`默认解析引擎：${selected.label}`}
          >
            <span>
              <strong>{selected.label}</strong>
              <small>{selected.description}</small>
            </span>
            <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          </button>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className={styles.parserTrigger}
            disabled={disabled}
            aria-label={`选择解析器：${selected.label}`}
          >
            <span className={styles.parserPrefix}>解析器:</span>
            <span className={styles.parserName}>{selected.label}</span>
            <ChevronDown className="size-3 shrink-0" />
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className={styles.parserDialog} showCloseButton={false} aria-modal="true">
        <header className={styles.parserDialogHeader}>
          <DialogTitle className="text-sm">选择解析器</DialogTitle>
          <DialogDescription className={styles.parserSubtitle} title={filename}>
            {filename ? `适用于 ${filename}，不可用的选项已标注原因` : '设置新上传文档的默认解析器'}
          </DialogDescription>
        </header>
        <div className={styles.parserDialogBody}>
          <div className={styles.parserSearch}>
            <Search className="size-4" aria-hidden="true" />
            <Input
              aria-label="搜索解析器"
              placeholder="搜索名称或解析能力…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          {loading ? (
            <p role="status" className={styles.parserFeedback}>
              正在加载解析器状态…
            </p>
          ) : null}
          {error ? (
            <div role="alert" className={styles.parserFeedback}>
              <p>无法读取解析器状态，部分选项可能不可用</p>
              <Button type="button" size="sm" variant="ghost" onClick={() => detachPromise(refresh())}>
                重试
              </Button>
            </div>
          ) : null}
          <div className={styles.parserCards} aria-label="解析器列表">
            {options.map((option) => {
              const incompatible =
                filename !== undefined &&
                filename.length > 0 &&
                option.value !== 'auto' &&
                resolveParserBackendForFilename(filename, option.value).backend !== option.value
              const unavailable =
                option.value !== 'auto' && option.value !== 'basic' && parserBackendAvailable(option.value) !== true
              const isDisabled = incompatible || unavailable
              const notes = capabilities?.pdf_backends
                .find(
                  (backend) => normalizeParserBackendName(backend.name) === normalizeParserBackendName(option.value),
                )
                ?.notes?.trim()
              const reason = incompatible ? '当前文件格式不支持此解析器' : notes || '请在设置中启用并配置此解析器'
              const isSelected = selected.value === option.value
              return (
                <button
                  key={option.value}
                  type="button"
                  className={styles.parserCard}
                  disabled={isDisabled}
                  aria-pressed={isSelected}
                  onClick={() => {
                    onChange(option.value)
                    setOpen(false)
                  }}
                >
                  <span className={styles.parserCardHeading}>
                    <strong>{option.label}</strong>
                    {isSelected ? <Check className="size-4 shrink-0" aria-hidden="true" /> : null}
                  </span>
                  <span className={styles.parserBadges}>
                    {option.badge ? <span>{option.badge}</span> : null}
                    <span data-available={!isDisabled}>
                      {incompatible ? '不支持当前格式' : unavailable ? '需配置' : '可用'}
                    </span>
                  </span>
                  <span className={styles.parserDescription}>{option.description}</span>
                  {isDisabled ? <span className={styles.parserReason}>{reason}</span> : null}
                </button>
              )
            })}
          </div>
          {options.length === 0 ? (
            <p role="status" className={styles.parserFeedback}>
              没有匹配的解析器
            </p>
          ) : null}
        </div>
        <footer className={styles.parserDialogFooter}>
          <span>选择后在下一次解析生效</span>
          <DialogClose asChild>
            <Button type="button" variant="outline" size="sm">
              取消
            </Button>
          </DialogClose>
        </footer>
      </DialogContent>
    </Dialog>
  )
}
