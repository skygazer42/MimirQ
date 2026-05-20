import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('SamlOpsPanel source', () => {
  it('keeps SAML as metadata configuration instead of a raw exchange console', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'saml-ops-panel.tsx'), 'utf8')

    expect(src).toContain('SAML 单点登录')
    expect(src).toContain('下载 Metadata')
    expect(src).toContain('身份源尚未配置')
    expect(src).toContain('isSamlNotConfiguredMessage')
    expect(src).not.toContain('SAML SSO')
    expect(src).not.toContain('登录断言交换')
    expect(src).not.toContain('SAML Response')
    expect(src).not.toContain('交换登录断言')
    expect(src).not.toContain('OperationResultPanel')
  })
})
