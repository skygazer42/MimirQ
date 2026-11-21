type ChunkStrategyParamsPrimitive = null | boolean | number | string
type ChunkStrategyParams = Record<string, ChunkStrategyParamsPrimitive>

type ChunkStrategyParamsResult = { ok: true; value: ChunkStrategyParams | undefined } | { ok: false; error: string }

export function validateChunkStrategyParams(value: unknown): ChunkStrategyParamsResult {
  if (value === null || value === undefined) return { ok: true, value: undefined }
  if (typeof value !== 'object' || Array.isArray(value)) {
    return { ok: false, error: 'chunk_strategy_params 必须是 JSON Object（键值对）' }
  }

  const entries: [string, unknown][] = Object.entries(value)
  if (entries.length === 0) return { ok: true, value: {} }
  if (entries.length > 30) {
    return { ok: false, error: 'chunk_strategy_params 键过多（最多 30 个）' }
  }

  const cleaned: [string, ChunkStrategyParamsPrimitive][] = []
  for (const [rawKey, parameterValue] of entries) {
    const key = rawKey.trim()
    if (key === '') continue
    if (key.length > 80) return { ok: false, error: '存在过长 key（最长 80 字符）' }

    if (parameterValue === undefined) continue

    const isPrimitive =
      parameterValue === null ||
      typeof parameterValue === 'boolean' ||
      typeof parameterValue === 'number' ||
      typeof parameterValue === 'string'
    if (!isPrimitive) {
      return { ok: false, error: '只允许原始类型 value（null/bool/number/string），不允许嵌套对象/数组' }
    }
    if (typeof parameterValue === 'number' && !Number.isFinite(parameterValue)) {
      return { ok: false, error: '存在非法 number value（必须为有限数值）' }
    }
    if (typeof parameterValue === 'string' && parameterValue.length > 500) {
      return { ok: false, error: '存在过长 string value（最长 500 字符）' }
    }
    cleaned.push([key, parameterValue])
  }

  return { ok: true, value: cleaned.length === 0 ? undefined : Object.fromEntries(cleaned) }
}

export function parseChunkStrategyParamsJson(text: string): ChunkStrategyParamsResult {
  const trimmed = text.trim()
  if (trimmed === '') return { ok: true, value: undefined }

  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    return { ok: false, error: 'JSON 解析失败：请检查括号、引号与逗号' }
  }

  return validateChunkStrategyParams(parsed)
}
