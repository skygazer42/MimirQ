import { describe, expect, it } from 'vitest'

import { MODEL_PROVIDERS } from './models'

function provider(id: string) {
  return MODEL_PROVIDERS.find((item) => item.id === id)
}

describe('model provider catalog', () => {
  it('surfaces the refreshed latest flagship model families for major chat providers', () => {
    const openai = provider('openai')
    const anthropic = provider('anthropic')
    const deepseek = provider('deepseek')
    const zhipu = provider('zhipu')
    const qwen = provider('qwen')
    const moonshot = provider('moonshot')
    const ark = provider('ark')
    const lingyiwanwu = provider('lingyiwanwu')
    const qianfan = provider('qianfan')
    const siliconflow = provider('siliconflow')
    const openrouter = provider('openrouter')
    const together = provider('together')

    expect(openai?.models.map((m) => m.name)).toContain('gpt-5.4')
    expect(anthropic?.models.map((m) => m.name)).toContain('claude-opus-4.6')
    expect(deepseek?.models.map((m) => m.name)).toContain('deepseek-v3.2')
    expect(zhipu?.models.map((m) => m.name)).toContain('glm-5.1')
    expect(qwen?.models.map((m) => m.name)).toContain('qwen3.6-plus')
    expect(moonshot?.models.map((m) => m.name)).toContain('kimi-k2.5')
    expect(ark?.models.map((m) => m.name)).toContain('doubao-seed-2.0-pro')
    expect(lingyiwanwu?.models.map((m) => m.name)).toContain('yi-lightning')
    expect(qianfan?.models.map((m) => m.name)).toContain('ernie-5.0')
    expect(siliconflow?.models.map((m) => m.name)).toContain('glm-5.1')
    expect(openrouter?.models.map((m) => m.name)).toContain('openrouter/auto')
    expect(together?.models.map((m) => m.name)).toContain('meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8')
  })

  it('drops obviously stale legacy defaults from the curated chat provider list', () => {
    const allModelNames = MODEL_PROVIDERS.flatMap((item) => item.models.map((model) => model.name))

    expect(allModelNames).not.toContain('gpt-3.5-turbo')
    expect(allModelNames).not.toContain('claude-3-opus-20240229')
    expect(allModelNames).not.toContain('qwen-turbo')
    expect(allModelNames).not.toContain('moonshot-v1-8k')
    expect(allModelNames).not.toContain('ernie-3.5-8k')
  })
})
