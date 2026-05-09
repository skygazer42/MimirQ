import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('tenant permission helpers', () => {
  it('keeps frontend permission constants aligned with backend RBAC permissions', () => {
    const frontend = fs.readFileSync(path.resolve(__dirname, 'tenant-permissions.ts'), 'utf8')
    const backend = fs.readFileSync(path.resolve(__dirname, '../../app/services/rbac_service.py'), 'utf8')

    for (const permission of [
      'settings.read',
      'settings.write',
      'observability.read',
      'usage.read',
      'audit.read',
      'audit.manage',
      'table_sql.read',
      'lifecycle.manage',
    ]) {
      expect(frontend).toContain(permission)
      expect(backend).toContain(permission)
    }
  })
})
