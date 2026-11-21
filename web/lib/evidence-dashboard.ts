import { z } from 'zod'

const coverageBucketSchema = z.looseObject({
  key: z.string(),
  items: z.number(),
  references: z.number(),
})

const coverageHeatmapSchema = z.looseObject({
  x: z.array(z.string()),
  y: z.array(z.string()),
  z: z.array(z.array(z.number())),
  metric: z.string(),
})

const leadTimeSchema = z.looseObject({
  count: z.number(),
  p50_sec: z.number().nullish(),
  p90_sec: z.number().nullish(),
  mean_sec: z.number().nullish(),
})

const suiteDashboardSchema = z.looseObject({
  generated_at: z.string(),
  throughput: z.looseObject({
    window_days: z.number(),
    last_window: z.looseObject({ created: z.number(), reviewed: z.number(), approved: z.number() }),
    draft_to_reviewed: leadTimeSchema,
    reviewed_to_approved: leadTimeSchema,
    draft_to_approved: leadTimeSchema,
  }),
  coverage: z.looseObject({
    language: z.array(coverageBucketSchema),
    file_type: z.array(coverageBucketSchema),
    quality_bucket: z.array(coverageBucketSchema),
    channel: z.array(coverageBucketSchema),
    heatmaps: z.record(z.string(), coverageHeatmapSchema),
  }),
})

export type SuiteDashboard = z.infer<typeof suiteDashboardSchema>
export type CoverageHeatmap = z.infer<typeof coverageHeatmapSchema>
export type SuiteDashboardSnapshot = Readonly<{ data: SuiteDashboard; includeArchived: boolean }>

export function parseSuiteDashboard(value: unknown): SuiteDashboard {
  const dashboard = suiteDashboardSchema.parse(value)
  for (const heatmap of Object.values(dashboard.coverage.heatmaps)) {
    if (heatmap.z.length !== heatmap.y.length || heatmap.z.some((row) => row.length !== heatmap.x.length)) {
      throw new Error('覆盖热图的行列与坐标数量不一致')
    }
  }
  return dashboard
}
