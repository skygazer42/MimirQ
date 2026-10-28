"use client"

import { motion, useReducedMotion } from "framer-motion"
import { usePathname } from "next/navigation"

export function PageTransition({ children }: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname()
  const shouldReduceMotion = useReducedMotion()

  return (
    <motion.div
      key={pathname}
      initial={shouldReduceMotion ? { opacity: 0, y: 0, filter: "blur(0px)" } : { opacity: 0, y: 20, filter: "blur(5px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)", transitionEnd: { filter: "none" } }}
      exit={shouldReduceMotion ? { opacity: 0, y: 0, filter: "blur(0px)" } : { opacity: 0, y: -20, filter: "blur(5px)" }}
      transition={{
        ...(shouldReduceMotion ? { duration: 0.01 } : { type: "spring", stiffness: 260, damping: 20 }),
      }}
      className="flex-1 w-full h-full"
    >
      {children}
    </motion.div>
  )
}
