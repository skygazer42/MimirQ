import { z } from 'zod'

export function boundedNumberDraft(label: string, minimum: number, maximum: number) {
  return z
    .string()
    .trim()
    .min(1, `请填写${label}`)
    .transform(Number)
    .pipe(z.number({ error: `${label}必须是有限数值` }))
    .refine((value) => value >= minimum && value <= maximum, `${label}必须在${minimum}到${maximum}之间`)
}
