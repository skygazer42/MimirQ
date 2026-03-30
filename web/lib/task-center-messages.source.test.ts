import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(webRoot, relativePath), 'utf8')
}

describe('task center messages catalog source', () => {
  it('keeps task center copy sourced from the next-intl catalog', () => {
    const taskCenter = read('components/task-center.tsx')
    const messages = read('i18n/messages/zh-CN.ts')

    expect(taskCenter).toContain("import { useTranslations } from 'next-intl'")
    expect(taskCenter).toContain("const t = useTranslations('TaskCenter')")
    expect(taskCenter).toContain("const commonT = useTranslations('Common')")
    expect(taskCenter).toContain("t('title')")
    expect(taskCenter).toContain("t('monitor')")
    expect(taskCenter).toContain("t('sectionActive')")
    expect(taskCenter).toContain("t('sectionFailed')")
    expect(taskCenter).toContain("t('stages.queued')")
    expect(taskCenter).toContain("commonT('close')")
    expect(taskCenter).toContain("commonT('retry')")

    expect(messages).toContain('TaskCenter: {')
    expect(messages).toContain("title: '任务中心'")
    expect(messages).toContain("monitor: '监控'")
    expect(messages).toContain("sectionActive: '进行中'")
    expect(messages).toContain("sectionFailed: '失败/隔离'")
    expect(messages).toContain("stages: {")
    expect(messages).toContain("queued: '排队中'")
  })
})
