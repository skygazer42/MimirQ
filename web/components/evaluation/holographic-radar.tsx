"use client"

import { ResponsiveContainer, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, Tooltip } from 'recharts'
import { motion } from 'framer-motion'
import { cn } from "@/lib/utils"

interface HolographicRadarProps {
  data: Array<{ subject: string; score: number; fullMark: number }>
  className?: string
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-slate-900/90 backdrop-blur-md border border-cyan-500/30 p-3 rounded-lg shadow-xl shadow-cyan-500/10">
        <p className="text-cyan-400 font-bold text-xs uppercase tracking-wider mb-1">{label}</p>
        <div className="flex items-baseline gap-1">
            <span className="text-2xl font-mono text-white font-bold">{payload[0].value}</span>
            <span className="text-xs text-slate-400">/ 100</span>
        </div>
      </div>
    )
  }
  return null
}

export function HolographicRadar({ data, className }: HolographicRadarProps) {
  return (
    <div className={cn("relative aspect-square w-full max-w-[400px] mx-auto", className)}>
      {/* Background Glow */}
      <div className="absolute inset-0 bg-cyan-500/5 rounded-full blur-3xl -z-10" />
      
      {/* Scanning Animation */}
      <div className="absolute inset-0 rounded-full border border-cyan-500/10 overflow-hidden pointer-events-none">
         <motion.div 
            className="w-full h-1/2 bg-gradient-to-b from-transparent to-cyan-500/10 origin-bottom"
            animate={{ rotate: 360 }}
            transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
            style={{ position: 'absolute', top: 0, left: 0 }}
         />
      </div>

      <ResponsiveContainer width="100%" height="100%">
        <RadarChart cx="50%" cy="50%" outerRadius="70%" data={data}>
          <PolarGrid stroke="rgba(6, 182, 212, 0.2)" strokeDasharray="4 4" />
          <PolarAngleAxis 
            dataKey="subject" 
            tick={{ fill: 'rgba(148, 163, 184, 0.8)', fontSize: 10, fontWeight: 600 }} 
          />
          <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
          <Radar
            name="Score"
            dataKey="score"
            stroke="#06b6d4" // Cyan-500
            strokeWidth={2}
            fill="#06b6d4"
            fillOpacity={0.3}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ stroke: '#06b6d4', strokeWidth: 1 }} />
        </RadarChart>
      </ResponsiveContainer>
      
      {/* Decorative Corners */}
      <div className="absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-cyan-500/30 rounded-tl-lg" />
      <div className="absolute top-0 right-0 w-4 h-4 border-t-2 border-r-2 border-cyan-500/30 rounded-tr-lg" />
      <div className="absolute bottom-0 left-0 w-4 h-4 border-b-2 border-l-2 border-cyan-500/30 rounded-bl-lg" />
      <div className="absolute bottom-0 right-0 w-4 h-4 border-b-2 border-r-2 border-cyan-500/30 rounded-br-lg" />
    </div>
  )
}
