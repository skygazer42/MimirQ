"use client"

import { motion, useReducedMotion } from "framer-motion"
import { ReactNode } from "react"

interface ScrollRevealProps {
  children: ReactNode
  className?: string
  direction?: "up" | "down" | "left" | "right"
  delay?: number
}

export function ScrollReveal({ children, className, direction = "up", delay = 0 }: ScrollRevealProps) {
  const shouldReduceMotion = useReducedMotion()
  const variants = {
    hidden: {
      opacity: 0,
      y: direction === "up" ? 20 : direction === "down" ? -20 : 0,
      x: direction === "left" ? 20 : direction === "right" ? -20 : 0,
    },
    visible: {
      opacity: 1,
      y: 0,
      x: 0,
      transition: {
        type: "spring" as const,
        stiffness: 100,
        damping: 20,
        delay,
      },
    },
  }

  if (shouldReduceMotion) {
    return <div className={className}>{children}</div>
  }

  return (
    <motion.div
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-50px" }} // Trigger when 50px into view
      variants={variants}
      className={className}
    >
      {children}
    </motion.div>
  )
}
