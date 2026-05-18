import { describe, expect, it } from 'vitest'

import {
  canShowAdminControlledNavigationModule,
  normalizeNavigationModules,
} from './navigation-visibility'

describe('navigation visibility policy', () => {
  it('lets admins see every admin-controlled module regardless of the ordinary-user list', () => {
    expect(
      canShowAdminControlledNavigationModule(
        {
          account_id: 'admin-1',
          is_active: true,
          is_current: true,
          navigation_user_visible_modules: [],
          permissions: ['settings.read'],
          role: 'admin',
          tenant_id: 'tenant-1',
        },
        'knowledgeGraph'
      )
    ).toBe(true)
  })

  it('limits normal users to backend-approved module keys and ignores unknown values', () => {
    const access = {
      account_id: 'viewer-1',
      is_active: true,
      is_current: true,
      navigation_user_visible_modules: ['knowledgeGraph', 'reports', 'unknownModule'],
      permissions: [],
      role: 'viewer',
      tenant_id: 'tenant-1',
    }

    expect(normalizeNavigationModules(access.navigation_user_visible_modules)).toEqual([
      'knowledgeGraph',
      'reports',
    ])
    expect(canShowAdminControlledNavigationModule(access, 'knowledgeGraph')).toBe(true)
    expect(canShowAdminControlledNavigationModule(access, 'graphSnapshots')).toBe(false)
  })
})
