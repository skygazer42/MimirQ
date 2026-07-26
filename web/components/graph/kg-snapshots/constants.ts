import type {
  DeltaDirection,
  SnapshotInlineStatTone,
  SnapshotStudioNode,
} from './types'

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
  amber: 'from-warning to-warning ring-warning/30',
  blue: 'from-primary to-info ring-primary/30',
  green: 'from-success to-success ring-success/30',
  orange: 'from-warning to-destructive ring-warning/30',
  purple: 'from-accent to-primary ring-accent/30',
  rose: 'from-destructive to-destructive ring-destructive/30',
  teal: 'from-success to-info ring-success/30',
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

export const SNAPSHOT_HEADER_ACTION_CLASS =
  'h-8 rounded-full border-border/40 bg-card/58 px-3 text-[11px] font-medium text-muted-foreground shadow-none hover:border-primary/28 hover:bg-background/72 hover:text-foreground'
export const SNAPSHOT_ICON_ACTION_CLASS =
  'h-8 w-8 rounded-full border-border/36 bg-card/54 text-muted-foreground shadow-none hover:border-primary/28 hover:bg-background/72 hover:text-foreground'
export const SNAPSHOT_PRIMARY_COMPARE_CLASS =
  'h-10 w-full gap-2 rounded-full bg-primary text-sm font-semibold text-primary-foreground shadow-[0_16px_32px_-22px_hsl(var(--primary)/0.72)] transition-shadow hover:bg-primary/92 hover:shadow-[0_18px_38px_-24px_hsl(var(--primary)/0.72)]'
export const SNAPSHOT_SECONDARY_ACTION_CLASS =
  'h-8 gap-1.5 rounded-full border-border/38 bg-background/48 px-2 text-[11px] font-medium text-muted-foreground shadow-none hover:border-primary/28 hover:bg-background/72 hover:text-foreground'

export const DELTA_LABELS: Record<DeltaDirection, string> = {
  flat: 'flat',
  negative: 'decrease',
  positive: 'increase',
}
