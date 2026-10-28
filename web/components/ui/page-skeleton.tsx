import { Loader2 } from '@/components/icons'
import { BrandLogo } from '@/components/brand-logo'
import { Skeleton } from '@/components/ui/skeleton'

type SkeletonLayout = 'neutral' | 'table' | 'knowledge' | 'directory' | 'matrix' | 'settings'
type PageSkeletonProps = Readonly<{ layout: SkeletonLayout; label: string }>
const ROWS = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'] as const

function WorkspaceHeader({ settings = false }: Readonly<{ settings?: boolean }>) {
  return <div className={'flex shrink-0 items-center gap-3 border-b border-border bg-background px-6 sm:px-7 ' + (settings ? 'h-20 min-h-20' : 'h-[72px] min-h-[72px]')}><Skeleton className="h-6 w-36 rounded" /><div className="flex-1" /><Skeleton className="h-8 w-20 rounded-md" /></div>
}
function TableRows({ matrix = false, compact = false }: Readonly<{ matrix?: boolean; compact?: boolean }>) {
  return <div className="min-h-0 flex-1 overflow-hidden">
    <div className="flex h-[38px] items-center gap-8 border-b border-border bg-background px-6 sm:px-7"><Skeleton className="h-3 w-24 rounded" /><div className="flex-1" /><Skeleton className="h-3 w-14 rounded" /><Skeleton className="hidden h-3 w-14 rounded sm:block" /></div>
    {ROWS.map(key => <div key={key} data-skeleton-row className={'flex items-center gap-6 border-b border-border px-6 sm:px-7 ' + (compact ? 'h-[58px]' : 'h-[72px]')}><div className="min-w-0 flex-1 space-y-2"><Skeleton className="h-3.5 w-2/3 max-w-72 rounded" /><Skeleton className="h-3 w-2/5 max-w-44 rounded" /></div>{matrix ? <><Skeleton className="hidden h-3 w-12 rounded md:block" /><Skeleton className="hidden h-3 w-12 rounded sm:block" /></> : <Skeleton className="hidden h-3 w-24 rounded lg:block" />}<Skeleton className="h-3 w-12 rounded" /><Skeleton className="size-6 rounded" /></div>)}
  </div>
}
function Footer() {
  return <div className="flex h-[46px] min-h-[46px] items-center gap-4 border-t border-border bg-background px-6 sm:px-7"><Skeleton className="h-3 w-24 rounded" /><div className="flex-1" /><Skeleton className="h-3 w-20 rounded" /></div>
}
function DirectoryRows() {
  return <>{ROWS.map(key => <div key={key} className="space-y-2 border-b border-border px-6 py-4"><Skeleton className="h-3.5 w-3/4 rounded" /><Skeleton className="h-3 w-1/2 rounded" /></div>)}</>
}

export function PageSkeleton({ layout, label }: PageSkeletonProps) {
  const isSettings = layout === 'settings'
  return <div role="status" aria-live="polite" data-page-skeleton={layout} className="flex h-dvh min-h-0 w-full overflow-hidden bg-background font-sans text-foreground">
    <span className="sr-only">{label}</span>
    <div aria-hidden="true" className="flex h-full min-h-0 w-full">
      <aside className={'shrink-0 flex-col border-r border-sidebar-border bg-sidebar ' + (isSettings ? 'flex w-16' : 'hidden w-[264px] md:flex')}>
        <div className={'flex h-16 shrink-0 items-center ' + (isSettings ? 'justify-center' : 'px-5')}><BrandLogo decorative variant={isSettings ? 'mark' : 'lockup'} className={isSettings ? 'w-8' : 'w-[132px]'} /></div>
        <div className={isSettings ? 'hidden' : 'px-5 pt-4'}><Skeleton className="h-10 w-full rounded-md" /><Skeleton className="mt-6 h-3 w-28 rounded" /></div>
        <div className={'mt-5 min-h-0 flex-1 overflow-hidden ' + (isSettings ? 'px-5' : 'px-6')}>{ROWS.map(key => <Skeleton key={key} className={isSettings ? 'mb-6 size-5 rounded' : 'mb-6 h-3.5 w-4/5 rounded'} />)}</div>
        <div className={'flex shrink-0 items-center gap-3 border-t border-sidebar-border py-5 ' + (isSettings ? 'justify-center' : 'px-5')}><Skeleton className="size-9 rounded-full" /><Skeleton className={isSettings ? 'hidden' : 'h-3 w-28 rounded'} /></div>
      </aside>
      <div className="flex min-h-0 min-w-0 flex-1 bg-card">
        {layout === 'settings' ? <aside className="hidden w-[236px] shrink-0 flex-col border-r border-border bg-sidebar xl:flex"><div className="px-6 py-8"><Skeleton className="h-6 w-20 rounded" /></div><DirectoryRows /></aside> : null}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <WorkspaceHeader settings={isSettings} />
          {isSettings ? <div className="shrink-0 border-b border-border px-6 py-3 xl:hidden"><Skeleton className="h-9 w-full rounded-md" /></div> : null}
          {layout === 'neutral' ? <div className="flex min-h-0 flex-1 items-center justify-center gap-3 p-6 text-[14px] text-muted-foreground"><Loader2 className="size-5 animate-spin motion-reduce:animate-none" /><span>{label}</span></div> : null}
          {layout === 'table' || layout === 'knowledge' ? <><div className="flex h-16 shrink-0 items-center gap-4 border-b border-border px-6 sm:px-7"><Skeleton className="h-9 w-64 max-w-[60%] rounded-md" /><div className="flex-1" /><Skeleton className="h-8 w-20 rounded-md" /></div><TableRows compact={layout === 'knowledge'} /><Footer /></> : null}
          {layout === 'directory' ? <><div className="flex h-12 shrink-0 items-center gap-4 border-b border-border px-6"><Skeleton className="h-3 w-28 rounded" /><Skeleton className="h-3 w-20 rounded" /></div><div className="flex min-h-0 flex-1"><aside className="hidden w-[252px] shrink-0 overflow-hidden border-r border-border lg:block"><div className="border-b border-border p-4"><Skeleton className="h-9 w-full rounded-md" /></div><DirectoryRows /></aside><div className="flex min-w-0 flex-1 items-center justify-center gap-3 p-6 text-[14px] text-muted-foreground"><Loader2 className="size-5 animate-spin motion-reduce:animate-none" /><span>{label}</span></div></div><Footer /></> : null}
          {layout === 'matrix' ? <><div className="flex h-11 shrink-0 items-center gap-7 border-b border-border px-6 sm:px-7"><Skeleton className="h-3.5 w-20 rounded" /><Skeleton className="h-3.5 w-24 rounded" /><Skeleton className="hidden h-3.5 w-24 rounded sm:block" /></div><div className="flex h-16 shrink-0 items-center gap-4 border-b border-border px-6"><Skeleton className="h-8 w-44 rounded-md" /><div className="flex-1" /><Skeleton className="h-3 w-24 rounded" /></div><div className="flex min-h-0 flex-1"><TableRows matrix /><aside className="hidden w-[360px] shrink-0 space-y-5 overflow-hidden border-l border-border p-6 xl:block"><Skeleton className="h-4 w-40 rounded" />{ROWS.map(key => <Skeleton key={key} className="h-3 w-full rounded" />)}</aside></div><Footer /></> : null}
          {layout === 'settings' ? <div className="min-h-0 flex-1 overflow-hidden px-6 py-8 sm:px-10"><Skeleton className="h-7 w-36 rounded" /><Skeleton className="mt-3 h-3 w-64 max-w-full rounded" /><div className="mt-9">{ROWS.slice(0, 5).map(key => <div key={key} className="flex items-center gap-8 border-b border-border py-6"><Skeleton className="h-3.5 w-1/3 max-w-44 rounded" /><Skeleton className="h-9 min-w-0 flex-1 rounded-md" /></div>)}</div></div> : null}
        </div>
      </div>
    </div>
  </div>
}
