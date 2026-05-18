export const systemPageTokens = {
  heading: 'text-[13px] font-semibold tracking-[-0.01em] text-foreground',
  body: 'text-[12px] leading-[1.45] text-muted-foreground',
  subtle: 'text-[11px] leading-4 text-muted-foreground/80',
  microLabel: 'text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground',
  monoMeta: 'font-mono text-[11px] leading-4 text-muted-foreground',
  tableHead: 'text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground',
} as const

export const systemDenseControls = {
  outlineButton: 'h-8 gap-1.5 rounded-lg border-border/70 bg-background px-3 text-xs font-semibold',
  primaryButton: 'h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold',
  inlineAction: 'h-7 gap-1 rounded-md border-border/60 bg-background px-2 text-[11px] font-semibold',
  input: 'h-9 rounded-lg border-border/70 bg-background text-[12px]',
  selectTrigger: 'h-9 rounded-lg border-border/70 bg-background text-[12px]',
  iconGhost: 'h-8 w-8 rounded-lg',
} as const

export const systemWorkbenchTokens = {
  panel: 'rounded-lg border-border/70 bg-background shadow-none',
  panelMuted: 'rounded-lg border-border/60 bg-muted/10 shadow-none',
  divider: 'border-border/70',
} as const

export const settingsTextTokens = {
  sectionTitle: 'text-sm font-semibold tracking-[-0.01em] text-slate-800',
  sectionIcon: 'h-4 w-4 text-blue-500',
  sectionBadge:
    'rounded-full border border-blue-100 bg-blue-50/70 px-2 py-0.5 text-[11px] font-medium text-blue-600',
  panelTitle: 'text-[12px] font-medium tracking-[-0.005em] text-slate-800',
  panelTitleIcon: 'h-4 w-4 text-slate-400',
  fieldLabel: 'text-[11px] font-medium text-slate-500',
  helpText: 'text-[11px] leading-4 text-slate-500/90',
  microText: 'text-[10px] leading-4 text-slate-500/80',
  valueText: 'text-slate-700',
} as const
