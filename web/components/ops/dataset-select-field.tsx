'use client'

import { useEffect, useState } from 'react'

import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { datasetApi } from '@/lib/api'
import { cn, detachPromise } from '@/lib/utils'

type DatasetOption = {
  id?: string
  name?: string | null
}

const ALL_DATASETS_VALUE = '__all_datasets__'

export function DatasetSelectField({
  value,
  onChange,
  label = '数据集',
  placeholder = '选择数据集',
  allLabel = '全部数据集',
  allowAll = false,
  className,
}: Readonly<{
  value: string
  onChange: (value: string) => void
  label?: string
  placeholder?: string
  allLabel?: string
  allowAll?: boolean
  className?: string
}>) {
  const [datasets, setDatasets] = useState<DatasetOption[]>([])
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setIsLoading(true)
    detachPromise(
      datasetApi
        .list({ limit: 200 })
        .then((response) => {
          if (!cancelled) setDatasets(response.items || [])
        })
        .catch(() => {
          if (!cancelled) setDatasets([])
        })
        .finally(() => {
          if (!cancelled) setIsLoading(false)
        })
    )

    return () => {
      cancelled = true
    }
  }, [])

  const selectedValue = value || (allowAll ? ALL_DATASETS_VALUE : '')

  return (
    <div className={cn('space-y-1', className)}>
      <Label className="text-[11px] font-medium text-muted-foreground">{label}</Label>
      <Select
        value={selectedValue}
        onValueChange={(next) => onChange(next === ALL_DATASETS_VALUE ? '' : next)}
        disabled={isLoading || (!allowAll && !datasets.length)}
      >
        <SelectTrigger className="h-8 text-xs">
          <SelectValue placeholder={isLoading ? '加载中...' : placeholder} />
        </SelectTrigger>
        <SelectContent>
          {allowAll ? <SelectItem value={ALL_DATASETS_VALUE}>{allLabel}</SelectItem> : null}
          {datasets.map((dataset) => {
            const id = String(dataset.id || '').trim()
            if (!id) return null
            return (
              <SelectItem key={id} value={id}>
                {dataset.name || id}
              </SelectItem>
            )
          })}
        </SelectContent>
      </Select>
    </div>
  )
}
