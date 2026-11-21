export function readNonEmptyString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const text = value.trim()
  return text.length === 0 ? undefined : text
}

export function toPrimitiveString(value: unknown, fallback = ''): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') return String(value)
  if (typeof value === 'symbol') return value.description ? `Symbol(${value.description})` : 'Symbol'
  return fallback
}

export function toTrimmedPrimitiveString(value: unknown, fallback = ''): string {
  const trimmed = toPrimitiveString(value, fallback).trim()
  return trimmed === '' ? fallback : trimmed
}
