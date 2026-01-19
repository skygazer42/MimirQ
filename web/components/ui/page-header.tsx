import { LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"

interface PageHeaderProps {
    title: string
    description?: React.ReactNode
    icon: LucideIcon
    iconColor?: string
    children?: React.ReactNode
    className?: string
    badge?: string
}

export function PageHeader({
    title,
    description,
    icon: Icon,
    iconColor = "text-primary",
    children,
    className,
    badge
}: PageHeaderProps) {
    return (
        <header className={cn("px-8 pt-8 pb-6 flex-shrink-0 relative z-10", className)}>
            <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-5">
                    {/* Icon Container with Glass Effect */}
                    <div className="relative group">
                        <div className={cn("absolute inset-0 blur-xl opacity-20 rounded-2xl transition-opacity group-hover:opacity-40", iconColor ? iconColor.replace('text-', 'bg-') : 'bg-sky-500')} />
                        <div className="relative w-14 h-14 rounded-2xl flex items-center justify-center bg-white border border-slate-200 shadow-sm transition-transform duration-500 group-hover:scale-105 group-hover:shadow-[0_0_30px_-10px_rgba(14,165,233,0.1)]">
                            <div className={cn("absolute inset-0 bg-gradient-to-br from-slate-50 to-transparent rounded-2xl opacity-50")} />
                            <Icon className={cn("w-7 h-7 relative z-10 transition-colors duration-300", iconColor)} />
                        </div>
                    </div>

                    <div className="pt-1">
                        <h1 className="text-3xl font-bold text-slate-900 tracking-tight flex items-center gap-3">
                            {title}
                            {badge && (
                                <span className={cn(
                                    "text-[10px] font-mono px-2 py-0.5 rounded border uppercase tracking-widest align-middle flex items-center",
                                    "bg-slate-100 border-slate-200 text-slate-500"
                                )}>
                                    {badge}
                                </span>
                            )}
                        </h1>
                        {description && (
                            <div className="text-sm text-slate-500 mt-2 leading-relaxed max-w-2xl flex items-center gap-2">
                                {description}
                            </div>
                        )}
                    </div>
                </div>

                {/* Actions Container */}
                {children && (
                    <div className="flex items-center gap-3 pt-1">
                        {children}
                    </div>
                )}
            </div>

            {/* Decorative Separator Gradient - Only if needed, otherwise rely on main layout */}
        </header>
    )
}
