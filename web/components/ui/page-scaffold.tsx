import type { LucideIcon } from "lucide-react"
import type { ComponentProps } from "react"

import { PageBody } from "@/components/ui/page-body"
import { PageContainer } from "@/components/ui/page-container"
import { PageHeader } from "@/components/ui/page-header"
import { PageHeaderBar } from "@/components/ui/page-header-bar"
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
  headerClassName,
  topClassName,
  toolbarClassName,
  toolbarBarClassName,
  bodyClassName,
  bodyContainerClassName,
}: PageScaffoldProps) {
  return (
    <>
      <div className="px-6 md:px-8 pt-6 md:pt-8 pb-5 md:pb-6 flex-shrink-0 relative z-10">
        <PageContainer size={size}>
          <PageHeader
            title={title}
            description={description}
            icon={icon}
            iconColor={iconColor}
            badge={badge}
            className={cn("p-0", headerClassName)}
          >
            {actions}
          </PageHeader>
        </PageContainer>
      </div>

      {top ? (
        <div className={cn("px-6 md:px-8 pb-6 flex-shrink-0 relative z-10", topClassName)}>
          <PageContainer size={size}>{top}</PageContainer>
        </div>
      ) : null}

      {toolbar ? (
        <PageHeaderBar className={cn("z-20", toolbarBarClassName)}>
          <div className={cn("px-6 md:px-8 py-3 md:py-4", toolbarClassName)}>
            <PageContainer size={size}>{toolbar}</PageContainer>
          </div>
        </PageHeaderBar>
      ) : null}

      <PageBody className={bodyClassName}>
        <PageContainer size={size} className={bodyContainerClassName}>
          {children}
        </PageContainer>
      </PageBody>
    </>
  )
}
