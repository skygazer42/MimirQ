export const settingsTextTokens = {
  sectionTitle: 'text-xl font-semibold leading-7 text-foreground',
  sectionIcon: 'h-4 w-4 text-muted-foreground',
  sectionBadge: 'rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground',
  panelTitle: 'text-[15px] font-semibold leading-6 text-foreground',
  panelTitleIcon: 'h-4 w-4 text-muted-foreground',
  fieldLabel: 'text-[15px] font-semibold leading-6 text-foreground',
  helpText: 'text-[13px] leading-5 text-muted-foreground',
  microText: 'text-xs leading-5 text-muted-foreground',
  valueText: 'text-foreground',
} as const

export const settingsLayoutTokens = {
  row: 'flex min-w-0 items-start justify-between gap-4 py-3',
  group:
    'grid min-w-0 gap-4 border-t border-border/60 py-5 first:border-t-0 first:pt-0 last:pb-0 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.5fr)] lg:gap-8',
  input: 'h-11 min-w-0 rounded-lg border-input bg-background text-base sm:h-10 sm:text-sm',
} as const

export const pipelinePickerTokens = {
  trigger: 'border-input bg-background text-foreground hover:bg-muted/30',
  menu: 'rounded-lg border-border/70 bg-background text-foreground shadow-strong',
  row: 'flex min-h-[60px] w-full items-center gap-3 rounded-md px-2.5 py-2.5 transition-colors duration-150 motion-reduce:transition-none focus-ring',
  selectedRow: 'bg-muted/70',
  idleRow: 'hover:bg-muted/45',
  iconFrame: 'bg-muted/60 text-muted-foreground',
  badge: 'bg-muted/60 text-muted-foreground',
} as const
