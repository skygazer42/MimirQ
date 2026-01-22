"use client"

import React, { useRef } from "react"
import { motion, useMotionValue, useReducedMotion, useSpring } from "framer-motion"

interface MagneticProps {
  children: React.ReactElement
  strength?: number
}

export function Magnetic({ children, strength = 0.5 }: MagneticProps) {
  const ref = useRef<HTMLDivElement>(null)
  const shouldReduceMotion = useReducedMotion()
  
  const x = useMotionValue(0)
  const y = useMotionValue(0)

  // Spring physics for smooth movement
  const springConfig = { stiffness: 150, damping: 15, mass: 0.1 }
  const springX = useSpring(x, springConfig)
  const springY = useSpring(y, springConfig)

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!ref.current) return
    
    const { clientX, clientY } = e
    const { height, width, left, top } = ref.current.getBoundingClientRect()
    
    // Calculate distance from center
    const middleX = clientX - (left + width / 2)
    const middleY = clientY - (top + height / 2)
    
    // Apply strength factor
    x.set(middleX * strength)
    y.set(middleY * strength)
  }

  const handleMouseLeave = () => {
    x.set(0)
    y.set(0)
  }

  return (
    <motion.div
      ref={ref}
      onMouseMove={shouldReduceMotion ? undefined : handleMouseMove}
      onMouseLeave={shouldReduceMotion ? undefined : handleMouseLeave}
      style={shouldReduceMotion ? undefined : { x: springX, y: springY }}
      className="inline-block"
    >
      {children}
    </motion.div>
  )
}
