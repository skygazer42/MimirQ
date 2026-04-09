export const analysisPageTokens = {
  pageSurface: 'bg-background',
  headerWrap: 'rounded-lg border border-border/70 bg-background',
  workbenchSurface: 'rounded-lg border border-border/70 bg-background',
  card: 'rounded-lg border border-border/70 bg-background shadow-none',
  cardMuted: 'rounded-lg border border-border/60 bg-muted/10 shadow-none',
  divider: 'border-border/70',
} as const

export const analysisTypographyTokens = {
  title: 'text-sm font-semibold tracking-[-0.01em] text-foreground',
  section: 'text-[13px] font-semibold tracking-[-0.01em] text-foreground',
  body: 'text-[12px] leading-[1.45] text-muted-foreground',
  subtle: 'text-[11px] leading-4 text-muted-foreground/80',
  label: 'text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground',
  mono: 'font-mono text-[11px] leading-4 tabular-nums text-foreground',
} as const

export const analysisDenseControls = {
  primaryButton: 'h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold',
  outlineButton: 'h-8 gap-1.5 rounded-lg border-border/70 bg-background px-3 text-xs font-semibold',
  inlineButton: 'h-7 gap-1 rounded-md border-border/60 bg-background px-2 text-[11px] font-semibold',
  input: 'h-9 rounded-lg border-border/70 bg-background text-[12px]',
  select: 'h-9 rounded-lg border-border/70 bg-background text-[12px]',
  iconButton: 'h-8 w-8 rounded-lg',
} as const
