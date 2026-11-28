import { Badge } from '@/components/ui/badge'

const VISIBLE_TAG_LIMIT = 10

export function DocumentTags({ tags }: Readonly<{ tags: readonly string[] }>) {
  const visibleTags = tags.slice(0, VISIBLE_TAG_LIMIT)
  const hiddenCount = tags.length - visibleTags.length

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {visibleTags.map((tag) => (
        <Badge key={tag} variant="soft" className="min-w-0 max-w-[12rem]" title={tag}>
          <span className="truncate">{tag}</span>
        </Badge>
      ))}
      {hiddenCount > 0 && <Badge variant="outline">+{hiddenCount}</Badge>}
    </div>
  )
}
