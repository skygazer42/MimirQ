import { getRequestConfig } from 'next-intl/server'

import zhCNMessages from './messages/zh-CN'
import { routing, type AppLocale } from './routing'

export default getRequestConfig(async ({ requestLocale }) => {
  const requestedLocale = await requestLocale
  const locale =
    typeof requestedLocale === 'string' &&
    routing.locales.includes(requestedLocale as AppLocale)
      ? requestedLocale
      : routing.defaultLocale

  return {
    locale,
    messages: zhCNMessages,
  }
})
