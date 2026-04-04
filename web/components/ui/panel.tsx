import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const panelVariants = cva(
  "flex flex-col rounded-xl border border-border/50 text-card-foreground shadow-soft",
  {
    variants: {
      variant: {
        default: "bg-card/95 transition-shadow duration-200 hover:shadow-md motion-reduce:transition-none",
        muted: "bg-muted/35",
        glass: "border-border/40 bg-card/50 backdrop-blur-xl",
      },
      padding: {
        none: "p-0",
        sm: "p-3",
        md: "p-4",
        lg: "p-6",
      },
    },
    defaultVariants: {
      variant: "default",
      padding: "md",
    },
  }
)

export interface PanelProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof panelVariants> {}

export function Panel({ className, variant, padding, ...props }: Readonly<PanelProps>) {
  return <div className={cn(panelVariants({ variant, padding }), className)} {...props} />
}
