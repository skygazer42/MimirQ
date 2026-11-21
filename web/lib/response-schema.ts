import { z } from 'zod'

export const integerSchema = z.number().int()
export const dateTimeSchema = z.iso.datetime({ offset: true, local: true })
export const recordSchema = z.custom<Record<string, unknown>>(
  (value) => typeof value === 'object' && value !== null && !Array.isArray(value),
)
export const integerRecordSchema = z.custom<Record<string, number>>((value) => {
  const result = recordSchema.safeParse(value)
  return result.success && Object.values(result.data).every((item) => integerSchema.safeParse(item).success)
})
export const stringRecordSchema = z.custom<Record<string, string>>((value) => {
  const result = recordSchema.safeParse(value)
  return result.success && Object.values(result.data).every((item) => typeof item === 'string')
})
