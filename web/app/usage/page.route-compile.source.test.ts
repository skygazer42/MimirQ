import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('usage page route compile guards', () => {
  it('uses PageScaffold supported props and defines window presets locally', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(src, 'const WINDOW_PRESETS = [')
    expectSourceToContain(src, 'bodyClassName=')
    expectSourceToContain(
      src,
      'pointer-events-none fixed inset-0 z-0 overflow-hidden'
    )
    expectSourceToContain(src, 'items-center justify-center')
    expectSourceToContain(
      src,
      "const dataStatus = summary ? '已就绪' : loading ? '同步中' : '未连接'"
    )
    expectSourceToContain(src, "if (value == null || value === '') return '0'")
    expectSourceToContain(
      src,
      "if (sec == null || !Number.isFinite(sec)) return '0ms'"
    )
    expectSourceToContain(src, 'label="数据状态"')
    expectSourceNotToContain(
      src,
      'className="bg-[#F8FAFC] relative overflow-hidden"'
    )
    expectSourceNotToContain(src, 'className="bg-slate-50/50"')
  })
})
