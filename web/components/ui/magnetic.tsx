"use client"

import React, { useEffect, useRef, useState } from "react"
import { motion, useMotionValue, useReducedMotion, useSpring } from "framer-motion"

interface MagneticProps {
  children: React.ReactElement
  strength?: number
}

export function Magnetic({ children, strength = 0.5 }: Readonly<MagneticProps>) {
  const ref = useRef<HTMLDivElement>(null)
  const shouldReduceMotion = useReducedMotion()
  const [isFinePointer, setIsFinePointer] = useState(false)
  
  const x = useMotionValue(0)
  const y = useMotionValue(0)

  // Spring physics for smooth movement
  const springConfig = { stiffness: 150, damping: 15, mass: 0.1 }
  const springX = useSpring(x, springConfig)
  const springY = useSpring(y, springConfig)

  const enabled = !shouldReduceMotion && isFinePointer

  useEffect(() => {
    if (globalThis.window === undefined) return

    const mq = globalThis.window.matchMedia("(pointer: fine)")
    const update = () => setIsFinePointer(mq.matches)
    update()

    mq.addEventListener("change", update)
    return () => mq.removeEventListener("change", update)
  }, [])

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!enabled) return
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

  if (!enabled) {
    return <div className="inline-block">{children}</div>
  }

  return (
    <motion.div
      ref={ref}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      style={{ x: springX, y: springY }}
      className="inline-block"
    >
      {children}
    </motion.div>
  )
}
