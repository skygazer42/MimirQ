'use client'

import { useEffect, useId } from 'react'

import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useDatasets } from '@/hooks/use-datasets'
import { formatApiError } from '@/lib/api-errors'
import { cn } from '@/lib/utils'

type DatasetSelectFieldProps = {
  value: string
  onChange: (value: string) => void
  label?: string
  placeholder?: string
  allLabel?: string
  allowAll?: boolean
  autoSelectFirst?: boolean
  className?: string
  labelClassName?: string
  triggerClassName?: string
}

const ALL_DATASETS_VALUE = '__all_datasets__'

export function DatasetSelectField({
  value,
  onChange,
  label = '数据集',
  placeholder = '选择数据集',
  allLabel = '全部数据集',
  allowAll = false,
  autoSelectFirst = false,
  className,
  labelClassName,
  triggerClassName,
}: Readonly<DatasetSelectFieldProps>) {
  const { datasets, isLoading, isFetching, error, refreshDatasets } = useDatasets()
  const selectId = useId()

  const selectedValue = value === '' && allowAll ? ALL_DATASETS_VALUE : value
  const firstDatasetId = datasets[0]?.id

  useEffect(() => {
    if (!autoSelectFirst || allowAll || value !== '' || error !== null || firstDatasetId === undefined) return
    onChange(firstDatasetId)
  }, [allowAll, autoSelectFirst, error, firstDatasetId, onChange, value])

  return (
    <div className={cn('min-w-0 space-y-1', className)}>
      <Label htmlFor={selectId} className={cn('text-[11px] font-medium text-muted-foreground', labelClassName)}>
        {label}
      </Label>
      <Select
        value={selectedValue}
        onValueChange={(next) => onChange(next === ALL_DATASETS_VALUE ? '' : next)}
        disabled={isLoading || (!allowAll && datasets.length === 0)}
      >
        <SelectTrigger id={selectId} aria-label={label} className={cn('h-8 text-xs', triggerClassName)}>
          <SelectValue placeholder={isLoading ? '加载中...' : placeholder} />
        </SelectTrigger>
        <SelectContent>
          {allowAll ? <SelectItem value={ALL_DATASETS_VALUE}>{allLabel}</SelectItem> : null}
          {value !== '' && !datasets.some((dataset) => dataset.id === value) ? (
            <SelectItem value={value} disabled>
              已选数据集：{value}
            </SelectItem>
          ) : null}
          {datasets.map((dataset) => (
            <SelectItem key={dataset.id} value={dataset.id}>
              {dataset.name === '' ? dataset.id : dataset.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {isFetching && !isLoading ? (
        <p role="status" className="text-xs text-muted-foreground">
          正在更新数据集目录，保留当前选择。
        </p>
      ) : null}
      {error !== null ? (
        <div role="alert" className="flex min-w-0 items-center gap-2 text-xs text-destructive">
          <span className="min-w-0 wrap-anywhere">{formatApiError(error, '加载数据集失败')}</span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 shrink-0 px-2 text-xs"
            disabled={isFetching}
            onClick={() => void refreshDatasets()}
          >
            重试
          </Button>
        </div>
      ) : null}
    </div>
  )
}
