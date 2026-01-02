export default function Loading() {
  return (
    <div className="flex h-screen items-center justify-center bg-slate-50/50 dark:bg-slate-950">
      <div className="flex items-center gap-3 text-slate-600 dark:text-slate-300">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600 dark:border-slate-700 dark:border-t-slate-200" />
        <span className="text-sm">页面加载中...</span>
      </div>
    </div>
  )
}

