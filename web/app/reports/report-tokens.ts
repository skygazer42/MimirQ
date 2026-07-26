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
  'text-xs font-medium tracking-[0.02em] text-muted-foreground/90'
export const REPORT_VALUE_CLASS =
  'truncate text-[0.875rem] font-semibold leading-5 tracking-[-0.01em] text-foreground'
export const REPORT_SUBTEXT_CLASS = 'text-xs leading-4 text-muted-foreground'
export const REPORT_METRIC_VALUE_CLASS =
  'text-[1.375rem] font-semibold leading-none tracking-[-0.04em] tabular-nums text-foreground'
export const REPORT_PANEL_TITLE_CLASS =
  'text-[0.9375rem] font-semibold leading-5 tracking-[-0.015em] text-foreground'
export const REPORT_TABLE_HEADER_CLASS =
  'text-[0.6875rem] font-medium uppercase tracking-[0.1em] text-muted-foreground'
export const REPORT_TABLE_ROW_CLASS = 'text-[0.8125rem] leading-5 text-foreground/85'
export const REPORT_PANEL_CLASS =
  'rounded-[1.15rem] border border-border/60 bg-card/92 p-3.5 shadow-[0_16px_36px_-30px_rgba(15,23,42,0.28)]'
export const REPORT_SECONDARY_ACTION_CLASS =
  'h-9 gap-1.5 rounded-xl border-border/60 bg-card/90 px-3 text-xs font-medium text-muted-foreground shadow-none hover:border-info/25 hover:bg-info/[0.10] hover:text-info'
export const REPORT_PRIMARY_ACTION_CLASS =
  'h-9 gap-1.5 rounded-xl bg-info px-3.5 text-xs font-semibold text-info-foreground shadow-[0_12px_24px_-14px_rgba(2,132,199,0.8)] hover:bg-info/90'
export const REPORT_FILTER_LABEL_CLASS =
  'text-xs font-medium tracking-[0.02em] text-muted-foreground'
export const REPORT_SELECT_TRIGGER_CLASS =
  'h-9 w-full rounded-xl border-border/60 bg-card/90 text-xs font-medium text-foreground/85 shadow-[0_1px_2px_rgba(15,23,42,0.04)] hover:border-info/25'
export const REPORT_SELECT_ITEM_CLASS =
  'py-2 text-xs font-medium text-foreground/85'
export const REPORT_METRIC_LEDGER_CLASS =
  'grid overflow-hidden rounded-[1.2rem] border border-border/60 bg-border/60 shadow-[0_18px_42px_-34px_rgba(15,23,42,0.35)] md:grid-cols-3 2xl:grid-cols-6'
