import type { DeltaDirection, SnapshotInlineStatTone } from './types'

export const DIFF_KEYS = ['docs', 'events', 'entities', 'links', 'relations'] as const

export const SNAPSHOT_COUNT_LABELS = {
  docs: '文档',
  events: '事件',
  entities: '实体',
  links: '关联',
  relations: '关系',
}

export const INLINE_STAT_TONE_CLASSES: Record<SnapshotInlineStatTone, string> = {
  muted: 'text-muted-foreground',
  neutral: 'text-foreground',
  positive: 'text-success',
  negative: 'text-destructive',
  warning: 'text-warning',
}

export const INLINE_STAT_VALUE_TONE_CLASSES: Record<SnapshotInlineStatTone, string> = {
  muted: 'text-muted-foreground',
  neutral: 'text-foreground',
  positive: 'text-success',
  negative: 'text-destructive',
  warning: 'text-warning',
}

export const DELTA_TEXT_CLASSES: Record<DeltaDirection, string> = {
  flat: 'text-muted-foreground',
  negative: 'text-destructive',
  positive: 'text-success',
}

export const DELTA_TINT_CLASSES: Record<DeltaDirection, string> = {
  flat: 'bg-muted/40 ring-border',
  negative: 'bg-destructive/10 ring-destructive/30',
  positive: 'bg-success/10 ring-success/30',
}

export const DELTA_BADGE_VARIANTS: Record<DeltaDirection, 'soft' | 'outline' | 'destructive'> = {
  flat: 'outline',
  negative: 'destructive',
  positive: 'soft',
}

export const DELTA_LABELS: Record<DeltaDirection, string> = {
  flat: '不变',
  negative: '减少',
  positive: '增加',
}
