"use client"

import { useState } from "react"
import { Navbar } from "@/components/navbar"
import { cn } from "@/lib/utils"

export function AppShell({ children }: { children: React.ReactNode }) {
  const [isSidebarOpen, setSidebarOpen] = useState(true)

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Navbar isSidebarOpen={isSidebarOpen} setSidebarOpen={setSidebarOpen} />
      
      <main className={cn(
        "flex-1 flex flex-col overflow-hidden relative transition-all duration-300 ease-in-out",
        // Mobile: full width. Desktop: push content if sidebar is open? 
        // Actually Navbar implementation handles width, main just takes flex-1.
        // But if we want specific margin adjustments or overlay behavior, we handle it here.
      )}>
        {children}
      </main>
    </div>
  )
}
