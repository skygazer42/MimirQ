'use client'

export const PIE_COLORS = [
  'hsl(var(--chart-5))',
  'hsl(var(--chart-1))',
  'hsl(var(--chart-2))',
  'hsl(var(--chart-4))',
  'hsl(var(--chart-3))',
  'hsl(var(--chart-6))',
  'hsl(var(--chart-7))',
]
export const CHART_TOOLTIP_STYLE = {
  borderRadius: 10,
  border: '1px solid hsl(var(--border))',
  background: 'hsl(var(--card) / 0.97)',
  color: 'hsl(var(--foreground))',
  boxShadow: '0 8px 26px hsl(var(--foreground) / 0.12)',
  padding: '8px 10px',
}
export const CHART_TOOLTIP_LABEL_STYLE = {
  color: 'hsl(var(--foreground))',
  fontWeight: 600,
}
export const CHART_TOOLTIP_CURSOR = { fill: 'hsl(var(--muted-foreground) / 0.08)' }
export const DEFAULT_PIPELINE_VERSION_VALUE = '__mimirq_default_pipeline_version__'
export const REPORT_LABEL_CLASS =
  'text-[0.6875rem] font-medium tracking-[0.02em] text-muted-foreground/90'
export const REPORT_VALUE_CLASS =
  'truncate text-[0.8125rem] font-semibold leading-4 tracking-[-0.01em] text-foreground'
export const REPORT_SUBTEXT_CLASS = 'text-[0.6875rem] leading-4 text-muted-foreground'
export const REPORT_METRIC_VALUE_CLASS =
  'text-[1.125rem] font-semibold leading-none tracking-[-0.035em] tabular-nums text-foreground'
export const REPORT_PANEL_TITLE_CLASS =
  'text-[0.875rem] font-semibold leading-5 tracking-[-0.015em] text-foreground'
export const REPORT_TABLE_HEADER_CLASS =
  'text-[0.6875rem] font-medium uppercase tracking-[0.1em] text-muted-foreground'
export const REPORT_TABLE_ROW_CLASS = 'text-[0.8125rem] leading-5 text-foreground/85'
export const REPORT_PANEL_CLASS =
  'rounded-2xl border border-info/15 bg-background/72 p-3 shadow-none'
export const REPORT_SECONDARY_ACTION_CLASS =
  'h-8 gap-1.5 rounded-lg border-info/15 bg-background/70 px-2.5 text-[11px] font-medium text-muted-foreground shadow-none hover:border-info/30 hover:bg-info/[0.08] hover:text-info'
export const REPORT_PRIMARY_ACTION_CLASS =
  'h-8 gap-1.5 rounded-lg bg-info px-3 text-[11px] font-semibold text-info-foreground shadow-none hover:bg-info/90'
export const REPORT_FILTER_LABEL_CLASS =
  'text-xs font-medium tracking-[0.02em] text-muted-foreground'
export const REPORT_SELECT_TRIGGER_CLASS =
  'h-8 w-full rounded-lg border-info/15 bg-info/[0.025] text-[11px] font-medium text-foreground/85 shadow-none hover:border-info/30'
export const REPORT_SELECT_ITEM_CLASS =
  'py-2 text-xs font-medium text-foreground/85'
export const REPORT_METRIC_LEDGER_CLASS =
  'grid overflow-hidden rounded-2xl border border-info/15 bg-info/15 shadow-none md:grid-cols-3 2xl:grid-cols-6'
