import { File, FileSignature, FileText } from "lucide-react"

import { cn } from "@/lib/utils"

type FileTypeIconProps = {
  type?: string | null
  className?: string
}

export function FileTypeIcon({ type, className }: Readonly<FileTypeIconProps>) {
  const t = String(type || "").trim().toLowerCase()
  const Icon =
    (() => {
    if (t === "pdf") {
        return FileSignature;
    }
    else {
        if (t === "md" || t === "txt") {
            return FileText;
        }
        else {
            return File;
        }
    }
})()

  return <Icon className={cn("h-4 w-4", className)} aria-hidden="true" />
}

