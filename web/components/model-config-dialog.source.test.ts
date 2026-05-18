import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('model config dialog source', () => {
  it('uses refreshed default API base URLs for major providers', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'model-config-dialog.tsx'), 'utf8')

    expect(src).toContain("openai: 'https://api.openai.com/v1'")
    expect(src).toContain("deepseek: 'https://api.deepseek.com/v1'")
    expect(src).toContain("zhipu: 'https://open.bigmodel.cn/api/paas/v4'")
    expect(src).toContain("qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1'")
    expect(src).toContain("'qwen-embedding': 'https://dashscope.aliyuncs.com/compatible-mode/v1'")
    expect(src).toContain("moonshot: 'https://api.moonshot.cn/v1'")
    expect(src).toContain("ark: 'https://ark.cn-beijing.volces.com/api/v3'")
    expect(src).toContain("lingyiwanwu: 'https://api.lingyiwanwu.com/v1'")
    expect(src).toContain("qianfan: 'https://qianfan.baidubce.com/v2'")
    expect(src).toContain("siliconflow: 'https://api.siliconflow.cn/v1'")
    expect(src).toContain("openrouter: 'https://openrouter.ai/api/v1'")
    expect(src).toContain("together: 'https://api.together.xyz/v1'")
  })
})
