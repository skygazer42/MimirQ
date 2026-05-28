import { cn } from "@/lib/utils"

type AppBackgroundProps = {
  className?: string
}

export function AppBackground({ className }: Readonly<AppBackgroundProps>) {
  return (
    <div aria-hidden="true" className={cn("pointer-events-none fixed inset-0 z-0 overflow-hidden", className)}>
      <div className="app-background__base absolute inset-0" />
      <div className="app-background__orb-primary absolute -left-[18rem] -top-[18rem] h-[42rem] w-[42rem] rounded-full blur-3xl" />
      <div className="app-background__orb-secondary absolute -right-[16rem] top-[4rem] h-[38rem] w-[38rem] rounded-full blur-3xl" />
    </div>
  )
}
