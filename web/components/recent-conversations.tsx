'use client'

import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'next/navigation'
import { useTranslations } from 'next-intl'

import { Conversation, ChevronRight } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Link, usePathname } from '@/i18n/navigation'
import { chatApi } from '@/lib/api/chat'
import { queryKeys } from '@/lib/query-keys'
import { matchesResourceId } from '@/lib/resource-id'
import { cn } from '@/lib/utils'

const RECENT_CONVERSATION_PARAMS = { limit: 6 }

export function RecentConversations({ enabled, onNavigate }: Readonly<{ enabled: boolean; onNavigate: () => void }>) {
  const t = useTranslations('Navbar')
  const pathname = usePathname()
  const isHistoryPage = pathname === '/history'
  const searchParams = useSearchParams()
  const selectedId = pathname === '/' ? searchParams.get('conversation') : null
  const conversationsQuery = useQuery({
    queryKey: queryKeys.chat.conversations(RECENT_CONVERSATION_PARAMS),
    queryFn: ({ signal }) => chatApi.listConversations(RECENT_CONVERSATION_PARAMS, { signal }),
    enabled,
    staleTime: 30_000,
  })
  const conversations = conversationsQuery.data?.items

  return (
    <section aria-labelledby="recent-conversations-title" className="mb-5">
      <div
        className={cn(
          'mb-1.5 flex min-h-8 items-center justify-between gap-2 rounded-lg px-3',
          isHistoryPage && 'bg-ring/10',
        )}
      >
        <h2 id="recent-conversations-title" className="text-xs font-medium text-muted-foreground">
          {isHistoryPage ? t('items.history') : t('recent.title')}
        </h2>
        <Link
          href="/history"
          prefetch={false}
          onNavigate={onNavigate}
          aria-current={isHistoryPage ? 'page' : undefined}
          className={cn(
            'rounded text-xs hover:text-foreground focus-ring',
            isHistoryPage ? 'font-medium text-foreground' : 'text-muted-foreground',
          )}
        >
          {t('recent.viewAll')}
        </Link>
      </div>
      {conversationsQuery.isLoading && (
        <div role="status" className="space-y-2 px-3 py-2">
          <span className="sr-only">{t('recent.loading')}</span>
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-4 w-3/5" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      )}
      {conversationsQuery.isError && (
        <div role="alert" className="px-3 py-2 text-xs text-muted-foreground">
          <p>{conversations?.length ? t('recent.refreshFailed') : t('recent.failed')}</p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="mt-1 px-0"
            disabled={conversationsQuery.isFetching}
            onClick={() => void conversationsQuery.refetch()}
          >
            {t('recent.retry')}
          </Button>
        </div>
      )}
      {conversations?.map((conversation) => {
        const title = conversation.title
        const label = title === null || title === undefined || title.trim() === '' ? conversation.id : title
        const selected = selectedId !== null && matchesResourceId(conversation.id, selectedId)
        return (
          <Link
            key={conversation.id}
            href={`/?conversation=${encodeURIComponent(conversation.id)}`}
            prefetch={false}
            onNavigate={onNavigate}
            aria-current={selected ? 'page' : undefined}
            title={label}
            className={cn(
              'group flex min-h-10 items-center gap-2.5 rounded-lg px-3 py-2 text-sm focus-ring hover:bg-muted',
              selected ? 'bg-ring/10 font-medium text-foreground' : 'text-sidebar-foreground/80',
            )}
          >
            <Conversation className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">{label}</span>
            <ChevronRight
              className="size-3 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100"
              aria-hidden="true"
            />
          </Link>
        )
      })}
      {conversationsQuery.isSuccess && conversationsQuery.data.items.length === 0 && (
        <p className="px-3 py-2 text-xs leading-5 text-muted-foreground">{t('recent.empty')}</p>
      )}
    </section>
  )
}
