"use client"

import { RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, Tooltip } from 'recharts'
import { motion, useReducedMotion } from 'framer-motion'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'
import { cn } from "@/lib/utils"

interface HolographicRadarProps {
  data: Array<{ subject: string; score: number; fullMark: number }>
  className?: string
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload?.length) {
    return (
      <div className="bg-popover/95 backdrop-blur-md border border-primary/30 p-3 rounded-lg shadow-strong">
        <p className="text-primary font-semibold text-xs uppercase mb-1">{label}</p>
        <div className="flex items-baseline gap-1">
            <span className="text-2xl font-mono text-foreground font-bold">{payload[0].value}</span>
            <span className="text-xs text-muted-foreground">/ 100</span>
        </div>
      </div>
    )
  }
  return null
}

export function HolographicRadar({ data, className }: Readonly<HolographicRadarProps>) {
  const reduceMotion = useReducedMotion()
  const primaryStroke = 'hsl(var(--primary))'
  const gridStroke = 'hsl(var(--primary) / 0.2)'
  const tickFill = 'hsl(var(--muted-foreground) / 0.8)'

  return (
    <div className={cn("relative aspect-square w-full max-w-[400px] mx-auto", className)}>
      {/* Background Glow */}
      <div className="absolute inset-0 bg-primary/5 rounded-full blur-2xl -z-10" />
      
      {/* Scanning Animation */}
      <div className="absolute inset-0 rounded-full border border-primary/10 overflow-hidden pointer-events-none">
         {reduceMotion ? (
            <div
              className="w-full h-1/2 bg-primary/5 origin-bottom"
              style={{ position: 'absolute', top: 0, left: 0 }}
            />
         ) : (
            <motion.div 
              className="w-full h-1/2 bg-primary/5 origin-bottom"
              animate={{ rotate: 360 }}
              transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
              style={{ position: 'absolute', top: 0, left: 0 }}
            />
         )}
      </div>

      <SafeResponsiveChart className="h-full w-full" minHeight={320}>
        <RadarChart cx="50%" cy="50%" outerRadius="70%" data={data}>
          <PolarGrid stroke={gridStroke} strokeDasharray="4 4" />
          <PolarAngleAxis 
            dataKey="subject" 
            tick={{ fill: tickFill, fontSize: 10, fontWeight: 600 }} 
          />
          <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
          <Radar
            name="Score"
            dataKey="score"
            stroke={primaryStroke}
            strokeWidth={2}
            fill={primaryStroke}
            fillOpacity={0.25}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ stroke: primaryStroke, strokeWidth: 1 }} />
        </RadarChart>
      </SafeResponsiveChart>
      
      {/* Decorative Corners */}
      <div className="absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-primary/30 rounded-tl-lg" />
      <div className="absolute top-0 right-0 w-4 h-4 border-t-2 border-r-2 border-primary/30 rounded-tr-lg" />
      <div className="absolute bottom-0 left-0 w-4 h-4 border-b-2 border-l-2 border-primary/30 rounded-bl-lg" />
      <div className="absolute bottom-0 right-0 w-4 h-4 border-b-2 border-r-2 border-primary/30 rounded-br-lg" />
    </div>
  )
}
