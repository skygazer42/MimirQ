import type { DeltaDirection, SnapshotInlineStatTone, SnapshotStudioNode } from './types'

export const DIFF_KEYS = ['docs', 'events', 'entities', 'links', 'relations'] as const

export const INLINE_STAT_TONE_CLASSES: Record<SnapshotInlineStatTone, string> = {
  muted: 'border-border/70 bg-card text-muted-foreground',
  neutral: 'border-border/70 bg-card text-foreground',
  positive: 'border-success/30 bg-success/5 text-success',
  negative: 'border-destructive/30 bg-destructive/5 text-destructive',
  warning: 'border-warning/30 bg-warning/5 text-warning',
}

export const INLINE_STAT_VALUE_TONE_CLASSES: Record<SnapshotInlineStatTone, string> = {
  muted: 'text-muted-foreground',
  neutral: 'text-foreground',
  positive: 'text-success',
  negative: 'text-destructive',
  warning: 'text-warning',
}

export const SNAPSHOT_NODE_TONE_CLASSES: Record<SnapshotStudioNode['tone'], string> = {
  amber: 'bg-warning/15 text-foreground ring-warning/40',
  blue: 'bg-info/15 text-foreground ring-info/40',
  green: 'bg-success/15 text-foreground ring-success/40',
  orange: 'bg-warning/15 text-foreground ring-warning/40',
  purple: 'bg-primary/10 text-foreground ring-primary/35',
  rose: 'bg-destructive/10 text-foreground ring-destructive/35',
  teal: 'bg-success/15 text-foreground ring-success/35',
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
  flat: 'flat',
  negative: 'decrease',
  positive: 'increase',
}
