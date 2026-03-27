import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const panelVariants = cva(
  "rounded-xl border border-border text-card-foreground shadow-soft",
  {
    variants: {
      variant: {
        default: "bg-card",
        muted: "bg-muted/40",
        glass: "bg-card/60 backdrop-blur-md",
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
