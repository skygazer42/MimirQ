import type { LucideIcon } from "lucide-react"

import { PageScaffold } from "@/components/ui/page-scaffold"
import type { PageTitleIconName } from "@/components/ui/page-title-icon"

type AnalysisPageShellProps = {
  title: string
  description?: React.ReactNode
  icon: LucideIcon
  iconImage?: PageTitleIconName
  iconColor?: string
  badge?: string
  actions?: React.ReactNode
  top?: React.ReactNode
  children: React.ReactNode
  size?: "5xl" | "6xl" | "7xl" | "full"
  showHeader?: boolean
  compact?: boolean
  bodyGutter?: "default" | "dense" | "none"
  headerClassName?: string
  topClassName?: string
  toolbarClassName?: string
  toolbarBarClassName?: string
  bodyClassName?: string
  bodyContainerClassName?: string
}

export function AnalysisPageShell({
  title,
  description,
  icon,
  iconImage,
  iconColor,
  badge,
  actions,
  top,
  children,
  size = 'full',
  showHeader = true,
  compact = true,
  bodyGutter,
  headerClassName,
  topClassName,
  toolbarClassName,
  toolbarBarClassName,
  bodyClassName,
  bodyContainerClassName,
}: Readonly<AnalysisPageShellProps>) {
  return (
    <PageScaffold
      title={title}
      description={description}
      icon={icon}
      iconImage={iconImage}
      iconColor={iconColor}
      badge={badge}
      actions={actions}
      top={top}
      size={size}
      showHeader={showHeader}
      compact={compact}
      bodyGutter={bodyGutter}
      headerClassName={headerClassName}
      topClassName={topClassName}
      toolbarClassName={toolbarClassName}
      toolbarBarClassName={toolbarBarClassName}
      bodyClassName={bodyClassName}
      bodyContainerClassName={bodyContainerClassName}
      density="system-dense"
    >
      {children}
    </PageScaffold>
  )
}
