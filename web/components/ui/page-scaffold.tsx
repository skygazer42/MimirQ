import type { LucideIcon } from "lucide-react"
import type { ComponentProps } from "react"

import { PageBody } from "@/components/ui/page-body"
import { PageContainer } from "@/components/ui/page-container"
import { PageHeader } from "@/components/ui/page-header"
import { PageHeaderBar } from "@/components/ui/page-header-bar"
import { PageToolbar } from "@/components/ui/page-toolbar"
import { cn } from "@/lib/utils"

type PageScaffoldProps = {
  title: string
  description?: React.ReactNode
  icon: LucideIcon
  iconColor?: string
  badge?: string
  actions?: React.ReactNode
  top?: React.ReactNode
  toolbar?: React.ReactNode
  children: React.ReactNode
  size?: ComponentProps<typeof PageContainer>["size"]
  showHeader?: boolean
  compact?: boolean
  density?: "default" | "system-dense"
  bodyGutter?: ComponentProps<typeof PageBody>["gutter"]
  headerClassName?: string
  topClassName?: string
  toolbarClassName?: string
  toolbarBarClassName?: string
  bodyClassName?: string
  bodyContainerClassName?: string
}

export function PageScaffold({
  title,
  description,
  icon,
  iconColor,
  badge,
  actions,
  top,
  toolbar,
  children,
  size = "6xl",
  showHeader = true,
  compact = true,
  density = "default",
  bodyGutter,
  headerClassName,
  topClassName,
  toolbarClassName,
  toolbarBarClassName,
  bodyClassName,
  bodyContainerClassName,
}: Readonly<PageScaffoldProps>) {
  const isSystemDense = density === "system-dense"

  return (
    <>
      {showHeader ? (
        <div
          className={cn(
            "flex-shrink-0 relative z-10",
            isSystemDense
              ? "px-3 md:px-4 lg:px-5 pt-4 md:pt-5 pb-2.5 md:pb-3"
              : compact
                ? "px-5 md:px-8 pt-5 md:pt-6 pb-3 md:pb-4"
                : "px-6 md:px-8 pt-6 md:pt-8 pb-5 md:pb-6"
          )}
        >
          <PageContainer size={size}>
            <PageHeader
              title={title}
              description={description}
              icon={icon}
              iconColor={iconColor}
              badge={badge}
              compact={compact}
              className={cn("p-0", headerClassName)}
            >
              {actions}
            </PageHeader>
          </PageContainer>
        </div>
      ) : null}

      {top ? (
        <div
          className={cn(
            "flex-shrink-0 relative z-10",
            isSystemDense
              ? "px-3 md:px-4 lg:px-5 pb-2.5"
              : compact
                ? "px-4 md:px-6 pb-3"
                : "px-6 md:px-8 pb-6",
            topClassName
          )}
        >
          <PageContainer size={size}>{top}</PageContainer>
        </div>
      ) : null}

      {toolbar ? (
        <PageHeaderBar className={cn("z-20", toolbarBarClassName)}>
          <div
            className={cn(
              isSystemDense
                ? "px-3 md:px-4 lg:px-5 py-2"
                : compact
                  ? "px-4 md:px-6 py-2 md:py-3"
                  : "px-6 md:px-8 py-3 md:py-4",
              toolbarClassName
            )}
          >
            <PageContainer size={size}>
              <PageToolbar>{toolbar}</PageToolbar>
            </PageContainer>
          </div>
        </PageHeaderBar>
      ) : null}

      <PageBody
        className={bodyClassName}
        compact={compact}
        gutter={bodyGutter ?? (isSystemDense ? "dense" : "default")}
      >
        <PageContainer size={size} className={bodyContainerClassName}>
          {children}
        </PageContainer>
      </PageBody>
    </>
  )
}
