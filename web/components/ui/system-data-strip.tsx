import { cn } from "@/lib/utils"
import { systemPageTokens } from "@/components/ui/system-page-tokens"

export type SystemDataStripItem = {
  id?: string
  label: string
  value: React.ReactNode
  hint?: React.ReactNode
  tone?: "default" | "success" | "warning" | "danger" | string
  mono?: boolean
}

type SystemDataStripProps = {
  items: readonly SystemDataStripItem[]
  className?: string
  minColumnWidth?: number
}

const TONE_CLASS: Record<NonNullable<SystemDataStripItem["tone"]>, string> = {
  default: "text-foreground",
  success: "text-success",
  warning: "text-warning",
  danger: "text-destructive",
}

export function SystemDataStrip({
  items,
  className,
  minColumnWidth = 176,
}: Readonly<SystemDataStripProps>) {
  if (!items.length) return null

  const cellWidth = Math.max(140, Math.floor(minColumnWidth))

  const resolveTone = (tone: SystemDataStripItem['tone']) => {
    if (!tone) return TONE_CLASS.default
    return tone in TONE_CLASS ? TONE_CLASS[tone as keyof typeof TONE_CLASS] : TONE_CLASS.default
  }

  return (
    <dl
      className={cn(
        "grid gap-px overflow-hidden rounded-lg border border-border/70 bg-border/60",
        className
      )}
      style={{ gridTemplateColumns: `repeat(auto-fit, minmax(${cellWidth}px, 1fr))` }}
    >
      {items.map((item, index) => (
        <div key={item.id || `${item.label}-${index}`} className="min-w-0 bg-background px-3 py-2.5">
          <dt className={cn(systemPageTokens.microLabel, "truncate")}>{item.label}</dt>
          <dd
            className={cn(
              "mt-1 truncate text-[13px] font-semibold tracking-[-0.01em]",
              item.mono && "font-mono tabular-nums",
              resolveTone(item.tone)
            )}
            title={typeof item.value === "string" ? item.value : undefined}
          >
            {item.value}
          </dd>
          {item.hint ? (
            <p className={cn(systemPageTokens.subtle, "mt-0.5 truncate")} title={typeof item.hint === "string" ? item.hint : undefined}>
              {item.hint}
            </p>
          ) : null}
        </div>
      ))}
    </dl>
  )
}
