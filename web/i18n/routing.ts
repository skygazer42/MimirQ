import { defineRouting } from 'next-intl/routing'

export const routing = defineRouting({
  locales: ['zh-CN'],
  defaultLocale: 'zh-CN',
  localePrefix: 'never',
})

export type AppLocale = (typeof routing.locales)[number]
