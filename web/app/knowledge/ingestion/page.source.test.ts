import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge ingestion page source', () => {
  it('wraps the client page in AppFrame and keeps the route-level description source markers', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { AppFrame } from '@/components/app-frame'")
    expect(src).toContain("dynamic(() => import('./operation-page-client')")
    expect(src).toContain("dynamic(() => import('./page-client')")
    expect(src).toContain('<AppFrame>')
    expect(src).toContain('</AppFrame>')
    expect(src).toContain('min-h-full bg-transparent')
    expect(src).toContain("searchParams.get('mode') === 'execution-monitor'")
    expect(src).toContain('ExecutionMonitorPageClient')
    expect(src).toContain('OperationPageClient')
    expect(src).not.toContain('bg-[#f6f9ff]')
    expect(src).not.toContain('Ingestion Workspace')
    expect(src).not.toContain('选择数据集和来源，提交真实入库任务。')
    expect(src).not.toContain('<span className="text-muted-foreground/60">|</span>')
  })
})
