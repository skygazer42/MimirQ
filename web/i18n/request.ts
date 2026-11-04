import { hasLocale } from 'next-intl'
import { getRequestConfig } from 'next-intl/server'

import zhCNMessages from './messages/zh-CN'
import { routing } from './routing'

export default getRequestConfig(async ({ requestLocale }) => {
  const requestedLocale = await requestLocale
  const locale = hasLocale(routing.locales, requestedLocale) ? requestedLocale : routing.defaultLocale

  return {
    locale,
    messages: zhCNMessages,
  }
})
