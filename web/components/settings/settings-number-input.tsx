'use client'

import { useState, type ComponentProps } from 'react'

import { Input } from '@/components/ui/input'
import { settingsLayoutTokens } from '@/components/ui/system-page-tokens'

type SettingsNumberInputProps = {
  value: number
  min?: number
  max?: number
  step?: 1 | 'any'
  onValueChange: (value: number) => void
} & Pick<ComponentProps<typeof Input>, 'id' | 'aria-label' | 'disabled' | 'className'>

export function SettingsNumberInput({
  value,
  min = 0,
  max,
  step = 1,
  onValueChange,
  className = settingsLayoutTokens.input,
  ...inputProps
}: Readonly<SettingsNumberInputProps>) {
  const [draft, setDraft] = useState<string | null>(null)

  function commitValue(input: HTMLInputElement) {
    const nextValue = input.valueAsNumber
    setDraft(null)
    if (input.validity.valid && Number.isFinite(nextValue) && nextValue !== value) {
      onValueChange(nextValue)
    }
  }

  return (
    <Input
      {...inputProps}
      type="number"
      min={min}
      max={max}
      step={step}
      value={draft ?? value}
      className={className}
      onChange={(event) => setDraft(event.currentTarget.value)}
      onKeyDown={(event) => {
        if (event.key === 'Enter') commitValue(event.currentTarget)
      }}
      onBlur={(event) => commitValue(event.currentTarget)}
    />
  )
}
