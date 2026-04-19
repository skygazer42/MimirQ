import { cn } from "@/lib/utils"

type CompactStatChipProps = {
  label: string
  value: React.ReactNode
  tone?: "default" | "success" | "warning" | "danger"
  mono?: boolean
  className?: string
}

const toneClass: Record<NonNullable<CompactStatChipProps['tone']>, string> = {
  default: 'text-foreground',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-destructive',
}

export function CompactStatChip({
  label,
  value,
  tone = 'default',
  mono = false,
  className,
}: Readonly<CompactStatChipProps>) {
  return (
    <div
      className={cn(
        'inline-flex items-center gap-2 rounded-md border border-border/70 bg-background px-2.5 py-1',
        className
      )}
    >
      <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</span>
      <span
        className={cn(
          'text-[11px] font-semibold',
          mono && 'font-mono tabular-nums',
          toneClass[tone]
        )}
      >
        {value}
      </span>
    </div>
  )
}
