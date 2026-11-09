import { test } from '@playwright/test'
import { openInjectedRouteError, openPublicState, publicStateFixture, publicStateShot } from './public-states.helpers'

test('export current public state components for visual review', async ({ page }) => {
  const state = await publicStateFixture(page)
  await openPublicState(page, '/settings/rbac', '无权限访问'); await publicStateShot(page, 'denied-desktop')
  await openInjectedRouteError(page, state); await publicStateShot(page, 'route-error-desktop')
  await page.setViewportSize({ width: 390, height: 844 })
  await openPublicState(page, '/__missing-boundary-fixture__', '页面不存在'); await publicStateShot(page, 'not-found-phone')
})
