"use client"

import { useEffect, useState } from "react"
import { motion, useMotionValue, useSpring } from "framer-motion"
import { usePathname } from "next/navigation"

export function FluidCursor() {
  const [variant, setVariant] = useState<"default" | "pointer" | "text" | "hidden">("default")
  const cursorX = useMotionValue(-100)
  const cursorY = useMotionValue(-100)

  const springConfig = { damping: 25, stiffness: 700 }
  const cursorXSpring = useSpring(cursorX, springConfig)
  const cursorYSpring = useSpring(cursorY, springConfig)

  const pathname = usePathname()

  useEffect(() => {
    // Hide default cursor
    document.body.style.cursor = 'none'

    // Add class to body to indicate custom cursor active
    document.body.classList.add('custom-cursor')

    const moveCursor = (e: MouseEvent) => {
      cursorX.set(e.clientX - 16) // Center the cursor (32px width / 2)
      cursorY.set(e.clientY - 16)
    }

    const checkHover = (e: MouseEvent) => {
      const target = e.target as HTMLElement

      // Check for buttons/links
      const isClickable = target.closest('button') || target.closest('a') || target.closest('[role="button"]')
      // Check for inputs/textareas
      const isInput = target.closest('input') || target.closest('textarea') || target.closest('[contenteditable="true"]')

      if (isInput) {
        setVariant("text")
      } else if (isClickable) {
        setVariant("pointer")
      } else {
        setVariant("default")
      }
    }

    const handleMouseLeave = () => setVariant("hidden")
    const handleMouseEnter = () => setVariant("default")

    window.addEventListener("mousemove", moveCursor)
    window.addEventListener("mouseover", checkHover)
    document.addEventListener("mouseleave", handleMouseLeave)
    document.addEventListener("mouseenter", handleMouseEnter)

    return () => {
      window.removeEventListener("mousemove", moveCursor)
      window.removeEventListener("mouseover", checkHover)
      document.removeEventListener("mouseleave", handleMouseLeave)
      document.removeEventListener("mouseenter", handleMouseEnter)
      document.body.style.cursor = 'auto'
      document.body.classList.remove('custom-cursor')
    }
  }, [pathname, cursorX, cursorY]) // Re-run on route change to ensure clean state

  // Variants for Framer Motion
  const variants = {
    default: {
      height: 12,
      width: 12,
      x: 10, // Offset to center relative to 32px box
      y: 10,
      backgroundColor: "var(--primary)",
      mixBlendMode: "difference" as const,
    },
    pointer: {
      height: 48,
      width: 48,
      x: -8,
      y: -8,
      backgroundColor: "rgba(var(--primary), 0.3)",
      mixBlendMode: "normal" as const,
      border: "1px solid var(--primary)",
    },
    text: {
      height: 24,
      width: 4,
      x: 14,
      y: 4,
      backgroundColor: "var(--primary)",
      borderRadius: 2,
      mixBlendMode: "difference" as const,
    },
    hidden: {
      opacity: 0
    }
  }

  // Only render on desktop to avoid issues on touch devices
  const [isDesktop, setIsDesktop] = useState(false)
  useEffect(() => {
    if (window.matchMedia("(pointer: fine)").matches) {
      setIsDesktop(true)
    }
  }, [])

  if (!isDesktop) return null

  return (
    <motion.div
      className="fixed top-0 left-0 z-[9999] pointer-events-none rounded-full"
      style={{
        translateX: cursorXSpring,
        translateY: cursorYSpring,
      }}
      variants={variants}
      animate={variant}
      transition={{ type: "spring", stiffness: 500, damping: 28 }}
    />
  )
}
