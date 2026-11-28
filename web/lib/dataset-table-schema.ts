import { z } from 'zod'

import { integerSchema, recordSchema } from '@/lib/response-schema'

const tableColumnSchema = z.looseObject({ name: z.string().min(1), dtype: z.string().nullable() })

export const tableAssetSchema = z.looseObject({
  table_id: z.string().min(1),
  document_id: z.uuid(),
  document_filename: z.string().nullable(),
  sheet_index: integerSchema.nonnegative(),
  sheet_name: z.string().nullable(),
  row_count: integerSchema.nonnegative(),
  col_count: integerSchema.nonnegative(),
  truncated: z.boolean(),
  columns: z.array(tableColumnSchema),
  sample_rows: z.array(recordSchema),
})

export const datasetTablesPageSchema = z
  .looseObject({
    total: integerSchema.nonnegative(),
    items: z.array(tableAssetSchema),
    next_skip: integerSchema.nonnegative().nullable(),
  })
  .refine((page) => page.total === page.items.length, '表格文档窗口的数量不一致，请重新读取')

export const tableQueryResponseSchema = z.looseObject({
  sql: z.string(),
  columns: z.array(z.string()),
  rows: z.array(z.array(z.unknown())),
  truncated: z.boolean(),
})

export const tableAskResponseSchema = z.looseObject({
  answer: z.string(),
  sql: z.string().nullable(),
  data: tableQueryResponseSchema.nullable(),
})
