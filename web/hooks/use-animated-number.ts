"use client"

import { useMotionValue, useSpring, useReducedMotion } from "framer-motion"
import { useEffect, useState } from "react"

interface UseAnimatedNumberOptions {
  /** Spring stiffness (default 120) */
  stiffness?: number
  /** Spring damping (default 20) */
  damping?: number
  /** Formatter function (default: Math.round + toLocaleString) */
  format?: (value: number) => string
}

const defaultFormat = (value: number) => Math.round(value).toLocaleString()

/**
 * Animated number transition using framer-motion spring physics.
 * Returns a formatted string that smoothly transitions between values.
 */
export function useAnimatedNumber(
  target: number,
  { stiffness = 120, damping = 20, format = defaultFormat }: UseAnimatedNumberOptions = {}
) {
  const shouldReduceMotion = useReducedMotion()
  const motionValue = useMotionValue(target)
  const spring = useSpring(motionValue, {
    stiffness,
    damping,
    restDelta: 0.5,
  })
  const [display, setDisplay] = useState(() => format(target))

  useEffect(() => {
    if (shouldReduceMotion) {
      setDisplay(format(target))
      return
    }
    motionValue.set(target)
  }, [target, motionValue, shouldReduceMotion, format])

  useEffect(() => {
    if (shouldReduceMotion) return
    const unsubscribe = spring.on("change", (v) => {
      setDisplay(format(v))
    })
    return unsubscribe
  }, [spring, shouldReduceMotion, format])

  return display
}
