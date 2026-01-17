"use client"

import React, { useRef } from "react"
import { motion, useMotionValue, useSpring, useTransform } from "framer-motion"
import { cn } from "@/lib/utils"

interface TiltCardProps {
  children: React.ReactNode
  className?: string
  onClick?: () => void
  onMouseEnter?: () => void
  onMouseLeave?: () => void
}

export function TiltCard({ children, className, onClick, onMouseEnter, onMouseLeave }: TiltCardProps) {
  const ref = useRef<HTMLDivElement>(null)

  const x = useMotionValue(0)
  const y = useMotionValue(0)

  // Spring physics for tilt
  const mouseX = useSpring(x, { stiffness: 300, damping: 30 })
  const mouseY = useSpring(y, { stiffness: 300, damping: 30 })

  // Transform mouse position to rotation degrees
  const rotateX = useTransform(mouseY, [-0.5, 0.5], ["5deg", "-5deg"])
  const rotateY = useTransform(mouseX, [-0.5, 0.5], ["-5deg", "5deg"])

  // Sheen gradient position
  const sheenX = useTransform(mouseX, [-0.5, 0.5], ["0%", "100%"])
  const sheenY = useTransform(mouseY, [-0.5, 0.5], ["0%", "100%"])

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
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

  const handleMouseLeave = () => {
    x.set(0)
    y.set(0)
    onMouseLeave?.()
  }

  return (
    <motion.div
      ref={ref}
      onMouseMove={handleMouseMove}
      onMouseEnter={onMouseEnter}
      onMouseLeave={handleMouseLeave}
      onClick={onClick}
      style={{
        rotateX,
        rotateY,
        transformStyle: "preserve-3d",
      }}
      className={cn("relative transition-all duration-200 ease-out will-change-transform perspective-1000", className)}
    >
      {/* Content */}
      <div className="relative z-10 h-full">
        {children}
      </div>

      {/* Sheen Effect */}
      <motion.div 
        className="absolute inset-0 z-20 pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-xl mix-blend-overlay"
        style={{
            background: `radial-gradient(circle at ${sheenX} ${sheenY}, rgba(255,255,255,0.3) 0%, transparent 60%)`
        }}
      />
    </motion.div>
  )
}
