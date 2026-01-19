"use client"

import { useEffect, useState } from "react"
import { motion, useMotionValue, useSpring } from "framer-motion"
import { usePathname } from "next/navigation"

export function FluidCursor() {
  const [variant, setVariant] = useState<"default" | "pointer" | "text" | "hidden">("default")
  const cursorX = useMotionValue(-100)
  const cursorY = useMotionValue(-100)

  // Slower spring for "follower" effect
  const springConfig = { damping: 25, stiffness: 300 }
  const cursorXSpring = useSpring(cursorX, springConfig)
  const cursorYSpring = useSpring(cursorY, springConfig)

  const pathname = usePathname()

  useEffect(() => {
    // IMPORTANT: Do NOT hide default cursor. User feedback indicated visibility issues.
    // document.body.style.cursor = 'none' 

    // Add class to body to indicate custom cursor active (optional, for other CSS hooks if needed)
    document.body.classList.add('custom-cursor-enabled')

    const moveCursor = (e: MouseEvent) => {
      // Center the cursor ring (typically larger than the dot)
      // Assuming roughly 32px or 40px ring
      cursorX.set(e.clientX - 16)
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
      // Ensure specific style cleanups
      document.body.style.cursor = ''
      document.body.classList.remove('custom-cursor-enabled')
    }
  }, [pathname, cursorX, cursorY])

  // Variants for Framer Motion
  const variants = {
    default: {
      height: 32,
      width: 32,
      x: 0,
      y: 0,
      backgroundColor: "transparent",
      border: "2px solid var(--primary)",
      borderRadius: "50%",
      opacity: 0.5,
      mixBlendMode: "normal" as const,
    },
    pointer: {
      height: 48, // Larger ring for clickable
      width: 48,
      x: -8,
      y: -8,
      backgroundColor: "rgba(var(--primary), 0.1)",
      border: "1px solid var(--primary)",
      borderRadius: "50%",
      opacity: 0.8,
      mixBlendMode: "normal" as const,
    },
    text: {
      height: 32,
      width: 32,
      x: 0,
      y: 0,
      backgroundColor: "transparent",
      border: "2px dashed var(--primary)", // Dashed ring for input
      borderRadius: "50%",
      opacity: 0.5,
      mixBlendMode: "normal" as const,
    },
    hidden: {
      opacity: 0
    }
  }

  // Only render on desktop
  const [isDesktop, setIsDesktop] = useState(false)
  useEffect(() => {
    if (window.matchMedia("(pointer: fine)").matches) {
      setIsDesktop(true)
    }
  }, [])

  if (!isDesktop) return null

  return (
    <motion.div
      className="fixed top-0 left-0 z-[9999] pointer-events-none"
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
