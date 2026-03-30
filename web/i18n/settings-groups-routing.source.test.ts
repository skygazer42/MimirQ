import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(webRoot, relativePath), 'utf8')
}

describe('next-intl settings groups routing source', () => {
  it('uses locale-aware navigation helpers across settings group pages', () => {
    const groupsPage = read('app/settings/groups/page.tsx')
    const groupDetailPage = read('app/settings/groups/[id]/page.tsx')

    expect(groupsPage).toContain('@/i18n/navigation')
    expect(groupsPage).not.toContain("import { useRouter } from 'next/navigation'")

    expect(groupDetailPage).toContain('@/i18n/navigation')
    expect(groupDetailPage).toContain("import { useParams } from 'next/navigation'")
    expect(groupDetailPage).not.toContain("import { useParams, useRouter } from 'next/navigation'")

    const localeGroupDetailWrapper = read('app/[locale]/settings/groups/[id]/page.tsx')
    expect(localeGroupDetailWrapper).toContain("export { default } from '../../../../settings/groups/[id]/page'")
  })
})
