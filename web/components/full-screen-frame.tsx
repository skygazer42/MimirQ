import { AppBackground } from "@/components/ui/app-background"
import { cn } from "@/lib/utils"

type FullScreenFrameProps = {
  children: React.ReactNode
  className?: string
  mainClassName?: string
  showBackground?: boolean
}

export function FullScreenFrame({
  children,
  className,
  mainClassName,
  showBackground = true,
}: FullScreenFrameProps) {
  return (
    <div className={cn("relative min-h-screen bg-background text-foreground", className)}>
      {showBackground && <AppBackground />}
      <main
        id="main-content"
        tabIndex={-1}
        className={cn("relative z-10 flex min-h-screen items-center justify-center px-6 py-10", mainClassName)}
      >
        {children}
      </main>
    </div>
  )
}

