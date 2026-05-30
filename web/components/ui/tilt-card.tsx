"use client"

import React, { useEffect, useRef, useState } from "react"
import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "framer-motion"
import { cn } from "@/lib/utils"

interface TiltCardProps {
  children: React.ReactNode
  className?: string
  onClick?: () => void
  onMouseEnter?: () => void
  onMouseLeave?: () => void
  onFocus?: React.FocusEventHandler<HTMLDivElement>
  onBlur?: React.FocusEventHandler<HTMLDivElement>
  selected?: boolean
}

export function TiltCard({ children, className, onClick, onMouseEnter, onMouseLeave, onFocus, onBlur, selected = false }: Readonly<TiltCardProps>) {
  const ref = useRef<HTMLDivElement>(null)
  const shouldReduceMotion = useReducedMotion()
  const [isFinePointer, setIsFinePointer] = useState(false)
  const interactive = typeof onClick === "function"

  const x = useMotionValue(0)
  const y = useMotionValue(0)

  // Spring physics for tilt
  const mouseX = useSpring(x, { stiffness: 300, damping: 30 })
  const mouseY = useSpring(y, { stiffness: 300, damping: 30 })

  // Transform mouse position to rotation degrees
  const rotateX = useTransform(mouseY, [-0.5, 0.5], ["5deg", "-5deg"])
  const rotateY = useTransform(mouseX, [-0.5, 0.5], ["-5deg", "5deg"])

  const enabled = !shouldReduceMotion && isFinePointer

  useEffect(() => {
    if (globalThis.window === undefined) return

    const mq = globalThis.window.matchMedia("(pointer: fine)")
    const update = () => setIsFinePointer(mq.matches)
    update()

    // Keep in sync on hybrid devices / pointer changes.
    try {
      mq.addEventListener("change", update)
      return () => mq.removeEventListener("change", update)
    } catch {
      // Safari < 14
      mq.addListener(update)
      return () => mq.removeListener(update)
    }
  }, [])

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!enabled) return
    if (!ref.current) return

    const rect = ref.current.getBoundingClientRect()
    
    // Normalize coordinates to -0.5 to 0.5
    const width = rect.width
    const height = rect.height
    
    const mouseXPos = e.clientX - rect.left
    const mouseYPos = e.clientY - rect.top
    
    const xPct = (mouseXPos / width) - 0.5
    const yPct = (mouseYPos / height) - 0.5

    x.set(xPct)
    y.set(yPct)
  }

  const handlePointerLeave = () => {
    x.set(0)
    y.set(0)
    onMouseLeave?.()
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!interactive) return
    // Only trigger when the card itself is focused, not when a nested control is.
    if (e.currentTarget !== e.target) return
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault()
      onClick?.()
    }
  }

  if (!interactive) {
    return (
      <div
        ref={ref}
        className={cn("relative", className)}
      >
        {children}
      </div>
    )
  }

  if (!enabled) {
    return (
      <div
        ref={ref}
        onClick={onClick}
        role="option"
        aria-selected={selected}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        onPointerEnter={() => onMouseEnter?.()}
        onPointerLeave={() => onMouseLeave?.()}
        onFocus={onFocus}
        onBlur={onBlur}
        className={cn("relative", className)}
      >
        {children}
      </div>
    )
  }

  return (
    <div
      ref={ref}
      onClick={onClick}
      role="option"
      aria-selected={selected}
      tabIndex={0}
      onKeyDown={handleKeyDown}
      onPointerMove={handlePointerMove}
      onPointerEnter={() => onMouseEnter?.()}
      onPointerLeave={handlePointerLeave}
      onFocus={onFocus}
      onBlur={onBlur}
      className={cn("relative perspective-1000", className)}
    >
      <motion.div
        style={{
          rotateX,
          rotateY,
          transformStyle: "preserve-3d",
        }}
        className="h-full transition-transform duration-200 ease-out"
      >
        {/* Content */}
        <div className="relative z-10 h-full">
          {children}
        </div>
      </motion.div>
    </div>
  )
}
