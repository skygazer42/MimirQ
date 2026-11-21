import type React from 'react'

/**
 * Utility to extract the actual DOM element type that a Radix primitive forwards refs to.
 */
export type RadixRef<T extends React.ElementType> = React.ComponentRef<T>

export function assignRef<T>(ref: React.Ref<T> | undefined, value: T | null): ReturnType<React.RefCallback<T>> {
  if (!ref) return
  if (typeof ref === 'function') {
    return ref(value)
  }
  ref.current = value
}
