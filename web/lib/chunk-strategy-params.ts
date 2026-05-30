export type ChunkStrategyParamsPrimitive = null | boolean | number | string
export type ChunkStrategyParams = Record<string, ChunkStrategyParamsPrimitive>

export type ChunkStrategyParamsValidateResult =
  | { ok: true; value: ChunkStrategyParams | undefined }
  | { ok: false; error: string }

export function validateChunkStrategyParams(value: unknown): ChunkStrategyParamsValidateResult {
  if (value == null) return { ok: true, value: undefined }
  if (typeof value !== 'object' || Array.isArray(value)) {
    return { ok: false, error: 'chunk_strategy_params 必须是 JSON Object（键值对）' }
  }

  const entries = Object.entries(value)
  if (entries.length > 30) {
    return { ok: false, error: 'chunk_strategy_params 键过多（最多 30 个）' }
  }

  const cleaned: Record<string, ChunkStrategyParamsPrimitive> = {}
  for (const [k, v] of entries) {
    const key = String(k || '').trim()
    if (!key) continue
    if (key.length > 80) return { ok: false, error: '存在过长 key（最长 80 字符）' }

    if (v === undefined) {
      continue
    }
    if (v === null || typeof v === 'boolean') {
      cleaned[key] = v
      continue
    }
    if (typeof v === 'number') {
      if (!Number.isFinite(v)) return { ok: false, error: '存在非法 number value（必须为有限数值）' }
      cleaned[key] = v
      continue
    }
    if (typeof v === 'string') {
      if (v.length > 500) return { ok: false, error: '存在过长 string value（最长 500 字符）' }
      cleaned[key] = v
      continue
    }

    return { ok: false, error: '只允许原始类型 value（null/bool/number/string），不允许嵌套对象/数组' }
  }

  return { ok: true, value: Object.keys(cleaned).length ? cleaned : undefined }
}

export function parseChunkStrategyParamsJson(text: string): ChunkStrategyParamsValidateResult {
  const raw = String(text || '')
  const trimmed = raw.trim()
  if (!trimmed) return { ok: true, value: undefined }

  let obj: unknown
  try {
    obj = JSON.parse(trimmed)
  } catch {
    return { ok: false, error: 'JSON 解析失败：请检查括号、引号与逗号' }
  }

  return validateChunkStrategyParams(obj)
}
