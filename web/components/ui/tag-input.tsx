import * as React from 'react'
import { X } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { normalizeTag, parseTagsText } from '@/lib/document-user-tags'

export function TagInput({
  value,
  onValueChange,
  placeholder,
  disabled,
  maxTags = 30,
  maxTagLen = 64,
  className,
  inputClassName,
}: Readonly<{
  value: string[]
  onValueChange: (next: string[]) => void
  placeholder?: string
  disabled?: boolean
  maxTags?: number
  maxTagLen?: number
  className?: string
  inputClassName?: string
  }>) {
    const t = useTranslations('CommonUi')
    const [draft, setDraft] = React.useState('')

    const tags = React.useMemo(() => (Array.isArray(value) ? value : []), [value])
    const resolvedPlaceholder = placeholder ?? t('tagInput.placeholder')

  const addTags = React.useCallback(
    (incoming: string[]) => {
      const cap = Math.max(0, Math.min(200, Number(maxTags || 0)))
      const seen = new Set(tags.map((t) => String(t || '').trim().toLowerCase()).filter(Boolean))
      const next = [...tags]

      for (const raw of incoming) {
        const norm = normalizeTag(raw, { maxLen: maxTagLen })
        if (!norm) continue
        const key = norm.trim().toLowerCase()
        if (!key || seen.has(key)) continue
        seen.add(key)
        next.push(norm)
        if (cap && next.length >= cap) break
      }

      onValueChange(next)
    },
    [maxTagLen, maxTags, onValueChange, tags]
  )

  const removeTag = React.useCallback(
    (tag: string) => {
      const key = String(tag || '').trim().toLowerCase()
      if (!key) return
      onValueChange(tags.filter((t) => String(t || '').trim().toLowerCase() !== key))
    },
    [onValueChange, tags]
  )

  const commitDraft = React.useCallback(() => {
    const text = String(draft || '')
    const parsed = parseTagsText(text, { maxTags, maxLen: maxTagLen })
    if (parsed.length) addTags(parsed)
    setDraft('')
  }, [addTags, draft, maxTagLen, maxTags])

  const onKeyDown: React.KeyboardEventHandler<HTMLInputElement> = (e) => {
    if (disabled) return
    if (e.key === 'Enter') {
      e.preventDefault()
      commitDraft()
      return
    }
    if (e.key === 'Backspace' && !draft.trim() && tags.length) {
      // Quick delete last tag when input is empty.
      const lastTag = tags.at(-1)
      if (lastTag) removeTag(lastTag)
    }
  }

  return (
    <div className={cn('space-y-2', className)}>
      {tags.length ? (
        <div className="flex flex-wrap items-center gap-2">
          {tags.map((tag) => (
            <Badge key={tag} variant="soft" className="gap-1 pr-1">
              <span className="max-w-[14rem] truncate">{tag}</span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-6 rounded-full hover:bg-muted"
                onClick={() => removeTag(tag)}
                disabled={disabled}
                aria-label={t('tagInput.removeLabel', { tag })}
              >
                <X className="size-3.5" aria-hidden="true" />
              </Button>
            </Badge>
          ))}
        </div>
      ) : null}

      <div className="flex items-center gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={() => {
            if (disabled) return
            if (draft.trim()) commitDraft()
          }}
          onPaste={(e) => {
            if (disabled) return
            const text = e.clipboardData?.getData('text') || ''
            const parsed = parseTagsText(text, { maxTags, maxLen: maxTagLen })
            if (!parsed.length) return
            // If paste contains multiple tags, treat as batch add.
            e.preventDefault()
            addTags(parsed)
          }}
          placeholder={resolvedPlaceholder}
          disabled={disabled}
          className={cn('h-10 rounded-xl', inputClassName)}
        />
        <Button
          type="button"
          variant="outline"
          className="h-10 rounded-xl"
          onClick={commitDraft}
          disabled={disabled || !draft.trim()}
        >
          {t('tagInput.add')}
        </Button>
      </div>
      <div className="text-[11px] text-muted-foreground">
        {tags.length}
        <span className="mx-1">/</span>
        {Math.max(0, Math.min(200, Number(maxTags || 0)))}
      </div>
    </div>
  )
}
