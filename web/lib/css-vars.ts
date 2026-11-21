function readHslTriplet(varName: string): { h: string; s: string; l: string } | null {
  if (globalThis.window === undefined) return null
  const value = getComputedStyle(document.documentElement).getPropertyValue(varName).trim()
  const [h, s, l] = value.split(/\s+/)
  return l === undefined ? null : { h, s, l }
}

// Returns a CSS color string like `hsl(210, 40%, 98%)` using the resolved HSL triplet stored in CSS variables.
export function getCssHslColor(varName: string, fallback: string): string {
  const triplet = readHslTriplet(varName)
  if (triplet === null) return fallback
  return `hsl(${triplet.h}, ${triplet.s}, ${triplet.l})`
}

export function getCssHslaColor(varName: string, alpha: number, fallback: string): string {
  const triplet = readHslTriplet(varName)
  if (triplet === null) return fallback
  const a = Number.isFinite(alpha) ? Math.min(1, Math.max(0, alpha)) : 1
  return `hsla(${triplet.h}, ${triplet.s}, ${triplet.l}, ${a})`
}
