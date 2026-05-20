"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

export interface SwitchProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onChange"> {
  readonly checked?: boolean
  readonly defaultChecked?: boolean
  readonly onCheckedChange?: (checked: boolean) => void
}

const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  (
    {
      className,
      checked: checkedProp,
      defaultChecked,
      onCheckedChange,
      disabled,
      ...props
    },
    ref
  ) => {
    const [uncontrolledChecked, setUncontrolledChecked] = React.useState(
      defaultChecked ?? false
    )

    const isControlled = typeof checkedProp === "boolean"
    const checked = isControlled ? checkedProp : uncontrolledChecked

    const toggle = () => {
      if (disabled) return
      const next = !checked
      if (!isControlled) setUncontrolledChecked(next)
      onCheckedChange?.(next)
    }

    return (
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        data-state={checked ? "checked" : "unchecked"}
        data-switch-state={checked ? "checked" : "unchecked"}
        disabled={disabled}
        onClick={(event) => {
          props.onClick?.(event)
          if (event.defaultPrevented) return
          toggle()
        }}
        ref={ref}
        className={cn(
          "peer inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50",
          checked ? "bg-primary" : "bg-input",
          className
        )}
        {...props}
      >
        <span
          aria-hidden="true"
          data-state={checked ? "checked" : "unchecked"}
          data-switch-state={checked ? "checked" : "unchecked"}
          className={cn(
            "pointer-events-none block h-5 w-5 rounded-full bg-background shadow-md ring-0 transition-all duration-150",
            checked
              ? "translate-x-[var(--switch-translate-checked,1.25rem)] scale-[1.02]"
              : "translate-x-[var(--switch-translate-unchecked,0rem)]"
          )}
        />
      </button>
    )
  }
)
Switch.displayName = "Switch"

export { Switch }
