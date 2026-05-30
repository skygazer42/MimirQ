export function isOneOf<const T extends readonly string[]>(
  values: T,
  value: string,
): value is T[number] {
  return values.includes(value)
}

export function coerceOneOf<const T extends readonly string[]>(
  values: T,
  value: string,
  fallback: T[number],
): T[number] {
  return isOneOf(values, value) ? value : fallback
}
