import { getFileTypeMeta } from '@/components/knowledge/file-type'
import { cn } from '@/lib/utils'

type FileTypeIconProps = {
  type?: string | null
  filename?: string | null
  className?: string
}

export function FileTypeIcon({ type, filename, className }: Readonly<FileTypeIconProps>) {
  const { icon: Icon } = getFileTypeMeta({ filename: filename || '', file_type: type || '' })
  return <Icon appearance="color" className={cn('h-4 w-4', className)} aria-hidden="true" />
}
