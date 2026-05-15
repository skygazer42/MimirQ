import Image from "next/image"

import { cn } from "@/lib/utils"

export const PAGE_TITLE_ICON_NAMES = [
  "access-review",
  "audit-log",
  "chat",
  "chunk-preview",
  "data-governance",
  "dataset",
  "diagnostics",
  "feedback-quality",
  "governance-config",
  "group-management",
  "ingestion-monitor",
  "ingestion-operation",
  "kg-retrieval-evaluation",
  "kg-snapshot",
  "knowledge-base",
  "knowledge-graph",
  "knowledge-management",
  "members-rbac",
  "parsing",
  "profile-discovery",
  "prompts",
  "qa-history",
  "quarantine-queue",
  "rag-visualization",
  "ragas-evaluation",
  "report-export",
  "retrieval-ablation",
  "settings",
  "usage-quota",
] as const

export type PageTitleIconName = (typeof PAGE_TITLE_ICON_NAMES)[number]

type PageTitleIconProps = {
  name: PageTitleIconName
  compact?: boolean
  className?: string
}

export function PageTitleIcon({
  name,
  compact = true,
  className,
}: Readonly<PageTitleIconProps>) {
  return (
    <Image
      src={`/page-title-icons/${name}.png`}
      alt=""
      aria-hidden="true"
      draggable={false}
      width={64}
      height={64}
      priority
      unoptimized
      className={cn(
        "pointer-events-none select-none object-contain",
        compact ? "size-8" : "size-10",
        className
      )}
    />
  )
}
