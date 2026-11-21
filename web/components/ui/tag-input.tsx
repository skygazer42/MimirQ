import { useState, type KeyboardEvent } from 'react'
import { X } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { appendTagText, tagKey } from '@/lib/tag-input'

type TagInputProps = {
  value: readonly string[]
  onValueChange: (next: string[]) => void
  placeholder?: string
  disabled?: boolean
  /** 0 表示不限数量。 */
  maxTags?: number
  maxTagLen?: number
  className?: string
  inputClassName?: string
  inputId?: string
}

export function TagInput({
  value,
  onValueChange,
  placeholder,
  disabled,
  maxTags = 30,
  maxTagLen = 64,
  className,
  inputClassName,
  inputId,
}: Readonly<TagInputProps>) {
  const t = useTranslations('CommonUi')
  const [draft, setDraft] = useState('')
  const preview = appendTagText(value, draft, { maxTags, maxLen: maxTagLen })
  const errorMessages = preview.issues.map((issue) =>
    issue === 'limit' ? t('tagInput.limitError', { maxTags }) : t('tagInput.lengthError', { maxLen: maxTagLen }),
  )
  let validationMessage = errorMessages.join(' ')
  if (validationMessage.length === 0 && draft.trim().length > 0) validationMessage = t('tagInput.pendingError')

  function commitText(text: string) {
    const result = appendTagText(value, text, { maxTags, maxLen: maxTagLen })
    onValueChange(result.tags)
    setDraft(result.pending)
  }

  function removeTag(tag: string) {
    const key = tagKey(tag)
    onValueChange(value.filter((current) => tagKey(current) !== key))
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (disabled || event.nativeEvent.isComposing) return
    if (event.key === 'Enter') {
      event.preventDefault()
      commitText(event.currentTarget.value)
    } else if (event.key === 'Backspace' && draft.length === 0 && value.length > 0) {
      event.preventDefault()
      onValueChange(value.slice(0, -1))
    }
  }

  return (
    <div className={cn('space-y-2', className)}>
      {value.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          {value.map((tag) => (
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
          id={inputId}
          ref={(input) => {
            if (input !== null) input.setCustomValidity(validationMessage)
          }}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={(event) => {
            if (!disabled && event.currentTarget.value.trim().length > 0) commitText(event.currentTarget.value)
          }}
          onPaste={(event) => {
            if (disabled) return
            const text = event.clipboardData.getData('text')
            if (text.trim().length === 0) return
            event.preventDefault()
            const result = appendTagText(value, text, { maxTags, maxLen: maxTagLen })
            onValueChange(result.tags)
            setDraft((current) => [current, result.pending].filter((part) => part.length > 0).join(', '))
          }}
          placeholder={placeholder ?? t('tagInput.placeholder')}
          disabled={disabled}
          aria-invalid={preview.issues.length > 0}
          className={cn('h-10 rounded-xl', inputClassName)}
        />
        <Button
          type="button"
          variant="outline"
          className="h-10 rounded-xl"
          onClick={() => commitText(draft)}
          disabled={disabled || draft.trim().length === 0}
        >
          {t('tagInput.add')}
        </Button>
      </div>
      {errorMessages.map((message) => (
        <p key={message} role="alert" className="break-words text-sm text-destructive">
          {message}
        </p>
      ))}
      <p className="text-[11px] text-muted-foreground">
        {value.length} / {maxTags === 0 ? t('tagInput.unlimited') : maxTags}
      </p>
    </div>
  )
}
