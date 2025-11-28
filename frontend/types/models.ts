/**
 * 模型提供商类型定义
 */

export interface ModelProvider {
  id: string
  name: string
  description: string
  icon: string // emoji or icon component name
  color: string // Tailwind color class
  isConfigured: boolean
  models: ModelConfig[]
  config?: ProviderConfig
}

export interface ModelConfig {
  id: string
  name: string
  displayName: string
  type: 'chat' | 'embedding' | 'image' | 'audio'
  contextWindow?: number
  maxTokens?: number
  pricing?: {
    input: number // per 1M tokens
    output: number
  }
}

export interface ProviderConfig {
  apiKey?: string
  apiBase?: string
  organizationId?: string
  projectId?: string
  temperature?: number
  maxTokens?: number
  timeout?: number
}

export const MODEL_PROVIDERS: ModelProvider[] = [
  {
    id: 'openai',
    name: 'OpenAI',
    description: 'GPT-4, GPT-3.5 系列模型',
    icon: 'openai', // 使用特殊标识,后续用SVG渲染
    color: 'emerald',
    isConfigured: false,
    models: [
      {
        id: 'gpt-4-turbo-preview',
        name: 'gpt-4-turbo-preview',
        displayName: 'GPT-4 Turbo',
        type: 'chat',
        contextWindow: 128000,
        maxTokens: 4096,
        pricing: { input: 10, output: 30 }
      },
      {
        id: 'gpt-4',
        name: 'gpt-4',
        displayName: 'GPT-4',
        type: 'chat',
        contextWindow: 8192,
        pricing: { input: 30, output: 60 }
      },
      {
        id: 'gpt-3.5-turbo',
        name: 'gpt-3.5-turbo',
        displayName: 'GPT-3.5 Turbo',
        type: 'chat',
        contextWindow: 16385,
        pricing: { input: 0.5, output: 1.5 }
      },
      {
        id: 'text-embedding-3-large',
        name: 'text-embedding-3-large',
        displayName: 'Embedding 3 Large',
        type: 'embedding',
        pricing: { input: 0.13, output: 0 }
      }
    ]
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    description: 'Claude 3 系列模型',
    icon: 'anthropic',
    color: 'orange',
    isConfigured: false,
    models: [
      {
        id: 'claude-3-opus',
        name: 'claude-3-opus-20240229',
        displayName: 'Claude 3 Opus',
        type: 'chat',
        contextWindow: 200000,
        pricing: { input: 15, output: 75 }
      },
      {
        id: 'claude-3-sonnet',
        name: 'claude-3-sonnet-20240229',
        displayName: 'Claude 3 Sonnet',
        type: 'chat',
        contextWindow: 200000,
        pricing: { input: 3, output: 15 }
      },
      {
        id: 'claude-3-haiku',
        name: 'claude-3-haiku-20240307',
        displayName: 'Claude 3 Haiku',
        type: 'chat',
        contextWindow: 200000,
        pricing: { input: 0.25, output: 1.25 }
      }
    ]
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    description: '高性价比的中文大模型',
    icon: 'deepseek',
    color: 'blue',
    isConfigured: false,
    models: [
      {
        id: 'deepseek-chat',
        name: 'deepseek-chat',
        displayName: 'DeepSeek Chat',
        type: 'chat',
        contextWindow: 32768,
        pricing: { input: 1, output: 2 }
      },
      {
        id: 'deepseek-coder',
        name: 'deepseek-coder',
        displayName: 'DeepSeek Coder',
        type: 'chat',
        contextWindow: 16384,
        pricing: { input: 1, output: 2 }
      }
    ]
  },
  {
    id: 'zhipu',
    name: '智谱 AI',
    description: 'GLM-4 系列模型',
    icon: 'zhipu',
    color: 'purple',
    isConfigured: false,
    models: [
      {
        id: 'glm-4',
        name: 'glm-4',
        displayName: 'GLM-4',
        type: 'chat',
        contextWindow: 128000,
        pricing: { input: 10, output: 10 }
      },
      {
        id: 'glm-4-air',
        name: 'glm-4-air',
        displayName: 'GLM-4 Air',
        type: 'chat',
        contextWindow: 128000,
        pricing: { input: 1, output: 1 }
      }
    ]
  },
  {
    id: 'qwen',
    name: '通义千问',
    description: '阿里云大模型服务',
    icon: 'qwen',
    color: 'sky',
    isConfigured: false,
    models: [
      {
        id: 'qwen-turbo',
        name: 'qwen-turbo',
        displayName: 'Qwen Turbo',
        type: 'chat',
        contextWindow: 8192,
        pricing: { input: 2, output: 6 }
      },
      {
        id: 'qwen-plus',
        name: 'qwen-plus',
        displayName: 'Qwen Plus',
        type: 'chat',
        contextWindow: 32768,
        pricing: { input: 4, output: 12 }
      },
      {
        id: 'qwen-max',
        name: 'qwen-max',
        displayName: 'Qwen Max',
        type: 'chat',
        contextWindow: 32768,
        pricing: { input: 40, output: 120 }
      }
    ]
  },
  {
    id: 'moonshot',
    name: 'Moonshot AI',
    description: 'Kimi 长文本大模型',
    icon: 'moonshot',
    color: 'indigo',
    isConfigured: false,
    models: [
      {
        id: 'moonshot-v1-8k',
        name: 'moonshot-v1-8k',
        displayName: 'Moonshot 8K',
        type: 'chat',
        contextWindow: 8192,
        pricing: { input: 12, output: 12 }
      },
      {
        id: 'moonshot-v1-32k',
        name: 'moonshot-v1-32k',
        displayName: 'Moonshot 32K',
        type: 'chat',
        contextWindow: 32768,
        pricing: { input: 24, output: 24 }
      },
      {
        id: 'moonshot-v1-128k',
        name: 'moonshot-v1-128k',
        displayName: 'Moonshot 128K',
        type: 'chat',
        contextWindow: 131072,
        pricing: { input: 60, output: 60 }
      }
    ]
  },
  {
    id: 'ollama',
    name: 'Ollama',
    description: '本地部署的开源模型',
    icon: 'ollama',
    color: 'gray',
    isConfigured: false,
    models: [
      {
        id: 'llama2',
        name: 'llama2',
        displayName: 'Llama 2',
        type: 'chat',
        contextWindow: 4096
      },
      {
        id: 'mistral',
        name: 'mistral',
        displayName: 'Mistral',
        type: 'chat',
        contextWindow: 8192
      },
      {
        id: 'qwen',
        name: 'qwen:14b',
        displayName: 'Qwen 14B',
        type: 'chat',
        contextWindow: 8192
      }
    ]
  },
  {
    id: 'local',
    name: '本地 Embedding',
    description: 'BGE 中文向量模型',
    icon: 'local',
    color: 'green',
    isConfigured: true,
    models: [
      {
        id: 'bge-large-zh-v1.5',
        name: 'BAAI/bge-large-zh-v1.5',
        displayName: 'BGE Large ZH v1.5',
        type: 'embedding',
        contextWindow: 512
      },
      {
        id: 'bge-base-zh-v1.5',
        name: 'BAAI/bge-base-zh-v1.5',
        displayName: 'BGE Base ZH v1.5',
        type: 'embedding',
        contextWindow: 512
      }
    ]
  }
]
