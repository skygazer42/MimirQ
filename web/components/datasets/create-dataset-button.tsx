import * as React from 'react'

import { Button, type ButtonProps } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const CreateDatasetButton = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ children = '新建数据集', className, ...props }, ref) => {
    return (
      <Button
        ref={ref}
        className={cn(
          'group h-auto gap-1.5 rounded-full border-[6px] border-[#c0dfff] bg-[#006aff] px-[1rem] py-[0.6rem] text-white shadow-[0_14px_28px_-20px_rgba(0,106,255,1)] transition-all duration-300 hover:border-[#b1d8ff] hover:bg-[#1b7aff] hover:shadow-[0_18px_32px_-20px_rgba(27,122,255,1)] active:border-[4px] focus-visible:ring-4 focus-visible:ring-[#c0dfff]/60 focus-visible:ring-offset-2 dark:border-[#5d9bff] dark:hover:border-[#84b6ff] dark:focus-visible:ring-[#5d9bff]/35 motion-reduce:transition-none md:px-[1.2rem] md:py-[0.68rem]',
          className
        )}
        {...props}
      >
        <span className="text-[0.92rem] font-bold tracking-[0.04em] md:text-[1rem] leading-none">
          {children}
        </span>
        <span className="flex h-full w-fit items-center justify-center pt-[3px]" aria-hidden="true">
          <svg
            viewBox="0 0 38 24"
            className="h-[18px] w-[24px] origin-left md:h-[20px] md:w-[26px] motion-safe:group-hover:[animation:dataset-jello-vertical_0.9s_both] motion-reduce:transform-none"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              d="M5 12H21"
              stroke="currentColor"
              strokeWidth="3.25"
              strokeLinecap="round"
            />
            <path
              d="M18.5 6.5L30.5 12L18.5 17.5"
              stroke="currentColor"
              strokeWidth="3.25"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      </Button>
    )
  }
)

CreateDatasetButton.displayName = 'CreateDatasetButton'

export { CreateDatasetButton }
