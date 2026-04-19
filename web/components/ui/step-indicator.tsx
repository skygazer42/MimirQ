'use client'

import { cn } from '@/lib/utils'
import { Check } from 'lucide-react'

interface Step {
  label: string
  description?: string
}

interface StepIndicatorProps {
  steps: Step[]
  currentStep: number
  className?: string
}

export function StepIndicator({
  steps,
  currentStep,
  className,
}: Readonly<StepIndicatorProps>) {
  return (
    <div className={cn('w-full', className)}>
      <div className="flex items-center justify-between">
        {steps.map((step, index) => {
          const isCompleted = index < currentStep
          const isCurrent = index === currentStep
          const isLast = index === steps.length - 1

          return (
            <div key={`${step.label}-${step.description || ''}`} className="flex items-center flex-1">
              {/* Step circle */}
              <div className="flex flex-col items-center">
                <div
                  className={cn(
                    'size-8 rounded-full flex items-center justify-center text-sm font-medium transition-colors duration-200 motion-reduce:transition-none',
                    (() => {
    if (isCompleted) {
        return 'bg-primary text-primary-foreground';
    }
    else if (isCurrent) {
            return 'bg-primary/10 text-primary ring-2 ring-primary ring-offset-2 ring-offset-background';
        }
        else {
            return 'bg-muted text-muted-foreground';
        }
})()
                  )}
                >
                  {isCompleted ? (
                    <Check className="w-4 h-4" />
                  ) : (
                    index + 1
                  )}
                </div>
                <span
                  className={cn(
                    'mt-2 text-xs font-medium whitespace-nowrap transition-colors motion-reduce:transition-none',
                    (() => {
    if (isCurrent) {
        return 'text-primary';
    }
    else if (isCompleted) {
            return 'text-foreground';
        }
        else {
            return 'text-muted-foreground';
        }
})()
                  )}
                >
                  {step.label}
                </span>
                {step.description && (
                  <span className="text-[11px] text-muted-foreground/70 mt-0.5">
                    {step.description}
                  </span>
                )}
              </div>

              {/* Connector line */}
              {!isLast && (
                <div className="flex-1 mx-2">
                  <div
                    className={cn(
                      'h-0.5 transition-colors duration-200 motion-reduce:transition-none',
                      isCompleted ? 'bg-primary/80' : 'bg-border'
                    )}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
