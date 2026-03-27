import type React from "react"

/**
 * Utility to extract the actual DOM element type that a Radix primitive forwards refs to.
 */
export type RadixRef<T extends React.ElementType> =
  React.ComponentPropsWithRef<T>["ref"] extends React.Ref<infer Element>
    ? Element
    : never

export function assignRef<T>(ref: React.Ref<T> | undefined, value: T | null): void {
  if (!ref) return
  if (typeof ref === "function") {
    ref(value)
    return
  }
  ;(ref as { current: T | null }).current = value
}
