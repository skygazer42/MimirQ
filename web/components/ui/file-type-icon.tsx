import { File, FileSignature, FileText } from "lucide-react"

import { cn } from "@/lib/utils"

type FileTypeIconProps = {
  type?: string | null
  className?: string
}

export function FileTypeIcon({ type, className }: FileTypeIconProps) {
  const t = String(type || "").trim().toLowerCase()
  const Icon =
    t === "pdf" ? FileSignature : t === "md" || t === "txt" ? FileText : File

  return <Icon className={cn("h-4 w-4", className)} aria-hidden="true" />
}

