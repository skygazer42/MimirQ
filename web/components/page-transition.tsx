"use client"

import { motion } from "framer-motion"
import { usePathname } from "next/navigation"

export function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()

  return (
    <motion.div
      key={pathname}
      initial={{ opacity: 0, y: 20, filter: "blur(5px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      exit={{ opacity: 0, y: -20, filter: "blur(5px)" }}
      transition={{
        type: "spring",
        stiffness: 260,
        damping: 20,
      }}
      className="flex-1 w-full h-full"
    >
      {children}
    </motion.div>
  )
}
