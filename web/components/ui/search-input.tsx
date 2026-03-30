'use client'

import * as React from "react"
import { Search, X } from "lucide-react"
import { useTranslations } from 'next-intl'

import { IconButton } from "@/components/ui/icon-button"
import { Input } from "@/components/ui/input"
import { assignRef } from "@/lib/radix-utils"
import { cn } from "@/lib/utils"

export type SearchInputProps = Readonly<Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  "type" | "value" | "onChange"
> & {
  value: string
  onValueChange: (next: string) => void
  containerClassName?: string
  inputClassName?: string
  onClear?: () => void
}>

export const SearchInput = React.forwardRef<HTMLInputElement, SearchInputProps>(function SearchInput(
  {
    value,
    onValueChange,
    containerClassName,
    inputClassName,
    onClear,
    placeholder,
    ...props
  },
  forwardedRef
) {
  const t = useTranslations('CommonUi')
  const inputRef = React.useRef<HTMLInputElement | null>(null)
  const resolvedPlaceholder = placeholder ?? t('searchInput.placeholder')

  const setRefs = (node: HTMLInputElement | null) => {
    inputRef.current = node
    assignRef(forwardedRef, node)
  }

  return (
    <div className={cn("relative", containerClassName)}>
      <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/70" />
      <Input
        ref={setRefs}
        type="search"
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
        placeholder={resolvedPlaceholder}
        className={cn("pl-9 pr-10", inputClassName)}
        {...props}
      />
      {value ? (
        <IconButton
          label={t('searchInput.clearLabel')}
          type="button"
          variant="ghost"
          className="absolute right-1.5 top-1/2 size-8 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          onClick={() => {
            onValueChange("")
            onClear?.()
            inputRef.current?.focus()
          }}
        >
          <X className="size-4" />
        </IconButton>
      ) : null}
    </div>
  )
})

SearchInput.displayName = "SearchInput"
