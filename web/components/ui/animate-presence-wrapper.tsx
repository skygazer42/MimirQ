"use client"

import { AnimatePresence, motion, useReducedMotion } from "framer-motion"
import type { HTMLMotionProps } from "framer-motion"
import * as React from "react"

const presets = {
  fade: {
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0 },
    transition: { duration: 0.2 },
  },
  "slide-up": {
    initial: { opacity: 0, y: 8 },
    animate: { opacity: 1, y: 0 },
    exit: { opacity: 0, y: 4 },
    transition: { duration: 0.22, ease: [0.22, 1, 0.36, 1] },
  },
  scale: {
    initial: { opacity: 0, scale: 0.95 },
    animate: { opacity: 1, scale: 1 },
    exit: { opacity: 0, scale: 0.97 },
    transition: { duration: 0.2, ease: [0.22, 1, 0.36, 1] },
  },
  "slide-left": {
    initial: { opacity: 0, x: 12 },
    animate: { opacity: 1, x: 0 },
    exit: { opacity: 0, x: -8 },
    transition: { duration: 0.22, ease: [0.22, 1, 0.36, 1] },
  },
} as const

type Preset = keyof typeof presets

interface AnimatedPresenceProps extends Omit<HTMLMotionProps<"div">, "initial" | "animate" | "exit" | "transition"> {
  show: boolean
  preset?: Preset
  children: React.ReactNode
  mode?: "wait" | "sync" | "popLayout"
  className?: string
}

export function AnimatedPresence({
  show,
  preset = "fade",
  children,
  mode = "wait",
  className,
  ...rest
}: AnimatedPresenceProps) {
  const shouldReduceMotion = useReducedMotion()
  const config = presets[preset]

  const motionProps = shouldReduceMotion
    ? { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 }, transition: { duration: 0.01 } }
    : config

  return (
    <AnimatePresence mode={mode}>
      {show && (
        <motion.div
          key="animated-presence"
          initial={motionProps.initial}
          animate={motionProps.animate}
          exit={motionProps.exit}
          transition={motionProps.transition}
          className={className}
          {...rest}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  )
}
