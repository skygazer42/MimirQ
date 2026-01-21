'use client'

import * as React from "react"
import { cn } from "@/lib/utils"

interface PageLoadingProps {
  /**
   * 中文提示文字，默认 "正在加载..."
   */
  message?: string
  /**
   * 屏幕阅读器提示，默认 "Loading"
   */
  srMessage?: string
  /**
   * 额外的容器样式
   */
  className?: string
}

const PageLoading = ({
  message = "正在加载...",
  srMessage = "Loading",
  className,
}: PageLoadingProps) => {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex-1 flex items-center justify-center",
        className
      )}
    >
      <div className="flex items-center gap-3 text-muted-foreground font-medium">
        <div
          className="h-6 w-6 animate-spin motion-reduce:animate-none rounded-full border-2 border-border border-t-primary"
          aria-hidden="true"
        />
        <span>{message}</span>
        <span className="sr-only">{srMessage}</span>
      </div>
    </div>
  )
}

PageLoading.displayName = "PageLoading"

export { PageLoading }
