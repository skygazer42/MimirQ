import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('document access dialog source', () => {
  it('submits through a React action form with useFormStatus-driven pending UI', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-access-dialog.tsx'), 'utf8')

    expect(src).toContain('useFormStatus')
    expect(src).toContain('function DocumentAccessSaveButton')
    expect(src).toContain('<form action={action}>')
    expect(src).toContain('const { pending } = useFormStatus()')
    expect(src).toContain('name="access_mode"')
    expect(src).toContain('name="access_group_ids_json"')
    expect(src).not.toContain('onSave')
    expect(src).not.toContain('isSaving')
  })
})
