export const QUARANTINE_PAGE_SIZE = 6
export const QUARANTINE_BACKGROUND_CLASS =
  'bg-background bg-[radial-gradient(circle_at_top,hsl(var(--info)/0.04),transparent_34rem)] dark:bg-background'
export const QUARANTINE_GRID_OVERLAY_CLASS = 'hidden'

export const STATUS_LABELS: Record<string, string> = {
  completed: '已解决',
  failed: '失败',
  quarantined: '待审核',
  pending: '待处理',
  processing: '处理中',
  cancelled: '已取消',
}

export const TYPO_EYEBROW =
  'text-[0.68rem] font-medium uppercase tracking-[0.24em] text-muted-foreground/64'
export const TYPO_SECTION_TITLE =
  'text-[0.98rem] font-medium tracking-[-0.015em] leading-[1.2] text-foreground/90'
export const TYPO_ITEM_TITLE =
  'text-[0.88rem] font-medium tracking-[-0.005em] leading-[1.3] text-foreground/92'
export const TYPO_META =
  'font-code tabular-nums text-[0.7rem] font-normal tracking-[0.01em] text-muted-foreground/62'
