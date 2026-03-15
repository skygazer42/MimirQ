export function getCssVarValue(varName: string): string | null {
  if (globalThis.window === undefined) return null
  const raw = getComputedStyle(document.documentElement).getPropertyValue(varName)
  const value = (raw || "").trim()
  return value || null
}

function parseHslTriplet(raw: string): { h: string; s: string; l: string } | null {
  const parts = (raw || "").trim().split(/\s+/g).filter(Boolean)
  if (parts.length < 3) return null
  const [h, s, l] = parts
  if (!h || !s || !l) return null
  return { h, s, l }
}

// Returns a CSS color string like `hsl(210, 40%, 98%)` using the resolved HSL triplet stored in CSS variables.
export function getCssHslColor(varName: string, fallback: string): string {
  const raw = getCssVarValue(varName)
  if (!raw) return fallback
  const triplet = parseHslTriplet(raw)
  if (!triplet) return fallback
  return `hsl(${triplet.h}, ${triplet.s}, ${triplet.l})`
}

export function getCssHslaColor(varName: string, alpha: number, fallback: string): string {
  const raw = getCssVarValue(varName)
  if (!raw) return fallback
  const triplet = parseHslTriplet(raw)
  if (!triplet) return fallback
  const a = Number.isFinite(alpha) ? Math.min(1, Math.max(0, alpha)) : 1
  return `hsla(${triplet.h}, ${triplet.s}, ${triplet.l}, ${a})`
}

