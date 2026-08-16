/**
 * 模型提供商类型定义
 */

export type ProviderCategory = 'model' | 'embedding' | 'reranker'

export interface ModelProvider {
  id: string
  name: string
  description: string
  icon: string // emoji or icon component name
  color: string // Tailwind color class
  category: ProviderCategory // 分类：模型/向量/重排序
  isConfigured: boolean
  models: ModelConfig[]
  config?: ProviderConfig
}

export interface ModelConfig {
  id: string
  name: string
  displayName: string
  type: 'chat' | 'embedding' | 'reranker' | 'image' | 'audio'
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
  model?: string
  organizationId?: string
  projectId?: string
  temperature?: number
  maxTokens?: number
  timeout?: number
}

export const MODEL_PROVIDERS: ModelProvider[] = [
  // ==================== 语言模型 ====================
  {
    id: 'openai',
    name: 'OpenAI',
    description: 'GPT-5.6 / GPT-5.5 / GPT-5.4 系列模型',
    icon: 'openai',
    color: 'emerald',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'gpt-5.6',
        name: 'gpt-5.6',
        displayName: 'GPT-5.6（旗舰别名）',
        type: 'chat',
        contextWindow: 1050000,
        maxTokens: 128000,
      },
      {
        id: 'gpt-5.6-sol',
        name: 'gpt-5.6-sol',
        displayName: 'GPT-5.6 Sol',
        type: 'chat',
        contextWindow: 1050000,
        maxTokens: 128000,
      },
      {
        id: 'gpt-5.6-terra',
        name: 'gpt-5.6-terra',
        displayName: 'GPT-5.6 Terra',
        type: 'chat',
        contextWindow: 1050000,
        maxTokens: 128000,
      },
      {
        id: 'gpt-5.6-luna',
        name: 'gpt-5.6-luna',
        displayName: 'GPT-5.6 Luna',
        type: 'chat',
        contextWindow: 1050000,
        maxTokens: 128000,
      },
      {
        id: 'gpt-5.4-mini',
        name: 'gpt-5.4-mini',
        displayName: 'GPT-5.4 mini',
        type: 'chat',
        contextWindow: 400000,
        maxTokens: 128000,
      },
      {
        id: 'gpt-5.5',
        name: 'gpt-5.5',
        displayName: 'GPT-5.5',
        type: 'chat',
        contextWindow: 1050000,
        maxTokens: 128000,
      },
      {
        id: 'gpt-5.4',
        name: 'gpt-5.4',
        displayName: 'GPT-5.4',
        type: 'chat',
        contextWindow: 1050000,
        maxTokens: 128000,
      },
      {
        id: 'gpt-5.4-nano',
        name: 'gpt-5.4-nano',
        displayName: 'GPT-5.4 nano',
        type: 'chat',
        contextWindow: 400000,
        maxTokens: 128000,
      },
      {
        id: 'gpt-5.5-pro',
        name: 'gpt-5.5-pro',
        displayName: 'GPT-5.5 pro',
        type: 'chat',
        contextWindow: 1050000,
        maxTokens: 128000,
      }
    ]
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    description: 'Claude 4.7 / 4.6 / 4.5 系列模型',
    icon: 'anthropic',
    color: 'orange',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'claude-sonnet-4-6',
        name: 'claude-sonnet-4-6',
        displayName: 'Claude Sonnet 4.6',
        type: 'chat',
        contextWindow: 1000000,
      },
      {
        id: 'claude-opus-4-7',
        name: 'claude-opus-4-7',
        displayName: 'Claude Opus 4.7',
        type: 'chat',
        contextWindow: 1000000,
      },
      {
        id: 'claude-haiku-4-5',
        name: 'claude-haiku-4-5',
        displayName: 'Claude Haiku 4.5',
        type: 'chat',
        contextWindow: 200000,
      }
    ]
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    description: 'DeepSeek V4 系列模型',
    icon: 'deepseek',
    color: 'blue',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'deepseek-v4-flash',
        name: 'deepseek-v4-flash',
        displayName: 'DeepSeek-V4-Flash',
        type: 'chat',
        contextWindow: 1000000,
        maxTokens: 384000,
      },
      {
        id: 'deepseek-v4-pro',
        name: 'deepseek-v4-pro',
        displayName: 'DeepSeek-V4-Pro',
        type: 'chat',
        contextWindow: 1000000,
        maxTokens: 384000,
      },
      {
        id: 'deepseek-chat',
        name: 'deepseek-chat',
        displayName: 'DeepSeek Chat（兼容别名）',
        type: 'chat',
        contextWindow: 1000000,
        maxTokens: 384000,
      },
      {
        id: 'deepseek-reasoner',
        name: 'deepseek-reasoner',
        displayName: 'DeepSeek Reasoner（兼容别名）',
        type: 'chat',
        contextWindow: 1000000,
        maxTokens: 384000,
      }
    ]
  },
  {
    id: 'zhipu',
    name: '智谱 AI',
    description: 'GLM-5 系列模型',
    icon: 'zhipu',
    color: 'purple',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'glm-5.1',
        name: 'glm-5.1',
        displayName: 'GLM-5.1',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'glm-5',
        name: 'glm-5',
        displayName: 'GLM-5',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'glm-5-turbo',
        name: 'glm-5-turbo',
        displayName: 'GLM-5-Turbo',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'glm-5v-turbo',
        name: 'glm-5v-turbo',
        displayName: 'GLM-5V-Turbo',
        type: 'image',
        contextWindow: 128000,
      },
      {
        id: 'glm-4.7',
        name: 'glm-4.7',
        displayName: 'GLM-4.7',
        type: 'chat',
        contextWindow: 128000,
      }
    ]
  },
  {
    id: 'qwen',
    name: '通义千问',
    description: 'Qwen3 / Coder / Omni 系列模型',
    icon: 'qwen',
    color: 'sky',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'qwen3-max',
        name: 'qwen3-max',
        displayName: 'Qwen3-Max',
        type: 'chat',
      },
      {
        id: 'qwen3.6-plus',
        name: 'qwen3.6-plus',
        displayName: 'Qwen3.6-Plus',
        type: 'chat',
      },
      {
        id: 'qwen3.6-flash',
        name: 'qwen3.6-flash',
        displayName: 'Qwen3.6-Flash',
        type: 'chat',
      },
      {
        id: 'qwen3-coder-next',
        name: 'qwen3-coder-next',
        displayName: 'Qwen3-Coder-Next',
        type: 'chat',
      },
      {
        id: 'qwen3.5-omni-plus',
        name: 'qwen3.5-omni-plus',
        displayName: 'Qwen3.5-Omni-Plus',
        type: 'image',
      }
    ]
  },
  {
    id: 'moonshot',
    name: 'Moonshot AI',
    description: 'Kimi K2.5 / K2 系列模型',
    icon: 'moonshot',
    color: 'indigo',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'kimi-k2.5',
        name: 'kimi-k2.5',
        displayName: 'Kimi K2.5',
        type: 'chat',
        contextWindow: 256000,
      },
      {
        id: 'kimi-k2-0905-preview',
        name: 'kimi-k2-0905-preview',
        displayName: 'Kimi K2 0905 Preview',
        type: 'chat',
        contextWindow: 256000,
      },
      {
        id: 'kimi-k2-turbo-preview',
        name: 'kimi-k2-turbo-preview',
        displayName: 'Kimi K2 Turbo Preview',
        type: 'chat',
        contextWindow: 256000,
      },
      {
        id: 'kimi-k2-thinking',
        name: 'kimi-k2-thinking',
        displayName: 'Kimi K2 Thinking',
        type: 'chat',
        contextWindow: 256000,
      },
      {
        id: 'moonshot-v1-128k',
        name: 'moonshot-v1-128k',
        displayName: 'Moonshot v1 128K',
        type: 'chat',
        contextWindow: 128000,
      }
    ]
  },
  {
    id: 'ollama',
    name: 'Ollama',
    description: '本地开源模型与量化模型',
    icon: 'ollama',
    color: 'gray',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'glm-5.1-local',
        name: 'glm-5.1',
        displayName: 'GLM-5.1',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'kimi-k2.5-local',
        name: 'kimi-k2.5',
        displayName: 'Kimi K2.5',
        type: 'chat',
        contextWindow: 200000,
      },
      {
        id: 'deepseek-v3.2-local',
        name: 'deepseek-v3.2',
        displayName: 'DeepSeek-V3.2',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'llama-4-maverick-local',
        name: 'llama-4-maverick',
        displayName: 'Llama 4 Maverick',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'qwen3-local',
        name: 'qwen3',
        displayName: 'Qwen3',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'mistral-latest-local',
        name: 'mistral-latest',
        displayName: 'Mistral Latest',
        type: 'chat',
        contextWindow: 128000,
      }
    ]
  },
  {
    id: 'ark',
    name: '火山引擎',
    description: 'Doubao-Seed 2.0 / 1.8 在线推理模型',
    icon: 'ark',
    color: 'orange',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'doubao-seed-2-0-pro-260215',
        name: 'doubao-seed-2-0-pro-260215',
        displayName: 'Doubao-Seed-2.0 Pro (260215)',
        type: 'chat',
      },
      {
        id: 'doubao-seed-2-0-lite-260428',
        name: 'doubao-seed-2-0-lite-260428',
        displayName: 'Doubao-Seed-2.0 Lite (260428)',
        type: 'chat',
      },
      {
        id: 'doubao-seed-2-0-mini-260428',
        name: 'doubao-seed-2-0-mini-260428',
        displayName: 'Doubao-Seed-2.0 Mini (260428)',
        type: 'chat',
      },
      {
        id: 'doubao-seed-2-0-code-preview-260215',
        name: 'doubao-seed-2-0-code-preview-260215',
        displayName: 'Doubao-Seed-2.0 Code Preview (260215)',
        type: 'chat',
      },
      {
        id: 'doubao-seed-1-8-251228',
        name: 'doubao-seed-1-8-251228',
        displayName: 'Doubao-Seed-1.8 (251228)',
        type: 'chat',
      }
    ]
  },
  {
    id: 'lingyiwanwu',
    name: '零一万物',
    description: 'Yi 系列模型',
    icon: 'lingyiwanwu',
    color: 'blue',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'yi-lightning',
        name: 'yi-lightning',
        displayName: 'Yi-Lightning',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'yi-large',
        name: 'yi-large',
        displayName: 'Yi-Large',
        type: 'chat',
        contextWindow: 128000,
      }
    ]
  },
  {
    id: 'qianfan',
    name: '百度千帆',
    description: 'ERNIE 5 系列模型',
    icon: 'qianfan',
    color: 'blue',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'ernie-5.0',
        name: 'ernie-5.0',
        displayName: 'ERNIE 5.0',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'ernie-4.5',
        name: 'ernie-4.5',
        displayName: 'ERNIE 4.5',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'ernie-4.5-vl',
        name: 'ernie-4.5-vl',
        displayName: 'ERNIE 4.5-VL',
        type: 'image',
        contextWindow: 128000,
      },
      {
        id: 'ernie-4.5-turbo',
        name: 'ernie-4.5-turbo',
        displayName: 'ERNIE 4.5 Turbo',
        type: 'chat',
        contextWindow: 128000,
      }
    ]
  },
  {
    id: 'siliconflow',
    name: 'SiliconFlow',
    description: '高性价比聚合平台',
    icon: 'siliconflow',
    color: 'purple',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'glm-5.1-sf',
        name: 'glm-5.1',
        displayName: 'GLM-5.1',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'kimi-k2.5-sf',
        name: 'kimi-k2.5',
        displayName: 'Kimi K2.5',
        type: 'chat',
        contextWindow: 200000,
      },
      {
        id: 'deepseek-v4-flash-sf',
        name: 'deepseek-v4-flash',
        displayName: 'DeepSeek-V4-Flash',
        type: 'chat',
        contextWindow: 1000000,
      },
      {
        id: 'qwen3-max-sf',
        name: 'qwen3-max',
        displayName: 'Qwen3-Max',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'minimax-m2.5-sf',
        name: 'minimax-m2.5',
        displayName: 'MiniMax-M2.5',
        type: 'chat',
        contextWindow: 128000,
      }
    ]
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    description: '多模型统一接入网关',
    icon: 'openrouter',
    color: 'indigo',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'auto',
        name: 'openrouter/auto',
        displayName: 'Auto (智能选择)',
        type: 'chat',
        contextWindow: 128000
      },
      {
        id: 'gpt-5.5-or',
        name: 'openai/gpt-5.5',
        displayName: 'GPT-5.5',
        type: 'chat',
        contextWindow: 1050000
      },
      {
        id: 'claude-opus-4.7-or',
        name: 'anthropic/claude-opus-4-7',
        displayName: 'Claude Opus 4.7',
        type: 'chat',
        contextWindow: 1000000
      },
      {
        id: 'glm-5.1-or',
        name: 'zhipu/glm-5.1',
        displayName: 'GLM-5.1',
        type: 'chat',
        contextWindow: 128000
      },
      {
        id: 'kimi-k2.5-or',
        name: 'moonshot/kimi-k2.5',
        displayName: 'Kimi K2.5',
        type: 'chat',
        contextWindow: 200000
      },
      {
        id: 'qwen3-max-or',
        name: 'qwen/qwen3-max',
        displayName: 'Qwen3-Max',
        type: 'chat',
        contextWindow: 128000
      }
    ]
  },
  {
    id: 'together',
    name: 'Together AI',
    description: '开源模型云端推理',
    icon: 'together',
    color: 'sky',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'llama-4-maverick',
        name: 'meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8',
        displayName: 'Llama 4 Maverick',
        type: 'chat',
        contextWindow: 131072,
      },
      {
        id: 'llama-4-scout',
        name: 'meta-llama/Llama-4-Scout-17B-16E-Instruct',
        displayName: 'Llama 4 Scout',
        type: 'chat',
        contextWindow: 131072,
      },
      {
        id: 'glm-5.1-together',
        name: 'zai-org/GLM-5.1',
        displayName: 'GLM-5.1',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'kimi-k2.5-together',
        name: 'moonshotai/Kimi-K2.5-Instruct',
        displayName: 'Kimi K2.5',
        type: 'chat',
        contextWindow: 200000,
      },
      {
        id: 'mixtral-latest',
        name: 'mistralai/Mixtral-8x22B-Instruct-v0.1',
        displayName: 'Mixtral Latest',
        type: 'chat',
        contextWindow: 65536,
      },
      {
        id: 'nemotron-latest',
        name: 'nvidia/Llama-3.1-Nemotron-70B-Instruct-HF',
        displayName: 'Nemotron Latest',
        type: 'chat',
        contextWindow: 131072,
      }
    ]
  },

  // ==================== Embedding 向量模型 ====================
  {
    id: 'openai-embedding',
    name: 'OpenAI Embedding',
    description: 'OpenAI 文本向量模型',
    icon: 'openai',
    color: 'emerald',
    category: 'embedding',
    isConfigured: false,
    models: [
      {
        id: 'text-embedding-3-large',
        name: 'text-embedding-3-large',
        displayName: 'Embedding 3 Large',
        type: 'embedding',
        contextWindow: 8191,
        pricing: { input: 0.13, output: 0 }
      },
      {
        id: 'text-embedding-3-small',
        name: 'text-embedding-3-small',
        displayName: 'Embedding 3 Small',
        type: 'embedding',
        contextWindow: 8191,
        pricing: { input: 0.02, output: 0 }
      }
    ]
  },
  {
    id: 'qwen-embedding',
    name: 'Qwen Embedding',
    description: '阿里云百炼文本向量模型',
    icon: 'qwen',
    color: 'sky',
    category: 'embedding',
    isConfigured: false,
    models: [
      {
        id: 'text-embedding-v4',
        name: 'text-embedding-v4',
        displayName: 'Text Embedding V4',
        type: 'embedding',
        contextWindow: 8192,
      },
      {
        id: 'text-embedding-v3',
        name: 'text-embedding-v3',
        displayName: 'Text Embedding V3',
        type: 'embedding',
        contextWindow: 8192,
      }
    ]
  },
  {
    id: 'local-embedding',
    name: '本地 Embedding',
    description: 'BGE 中文向量模型',
    icon: 'local-embedding',
    color: 'green',
    category: 'embedding',
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
      },
      {
        id: 'bge-m3',
        name: 'BAAI/bge-m3',
        displayName: 'BGE M3 (多语言)',
        type: 'embedding',
        contextWindow: 8192
      }
    ]
  },

  // ==================== Reranker 重排序模型 ====================
  {
    id: 'local-reranker',
    name: '本地 Reranker',
    description: 'BGE 重排序模型',
    icon: 'reranker',
    color: 'amber',
    category: 'reranker',
    isConfigured: true,
    models: [
      {
        id: 'bge-reranker-v2-m3',
        name: 'BAAI/bge-reranker-v2-m3',
        displayName: 'BGE Reranker v2 M3',
        type: 'reranker',
        contextWindow: 8192
      },
      {
        id: 'bge-reranker-large',
        name: 'BAAI/bge-reranker-large',
        displayName: 'BGE Reranker Large',
        type: 'reranker',
        contextWindow: 512
      },
      {
        id: 'bge-reranker-base',
        name: 'BAAI/bge-reranker-base',
        displayName: 'BGE Reranker Base',
        type: 'reranker',
        contextWindow: 512
      }
    ]
  },
  {
    id: 'cohere-reranker',
    name: 'Cohere Reranker',
    description: 'Cohere 云端重排序服务',
    icon: 'reranker',
    color: 'rose',
    category: 'reranker',
    isConfigured: false,
    models: [
      {
        id: 'rerank-english-v3.0',
        name: 'rerank-english-v3.0',
        displayName: 'Rerank English v3',
        type: 'reranker'
      },
      {
        id: 'rerank-multilingual-v3.0',
        name: 'rerank-multilingual-v3.0',
        displayName: 'Rerank Multilingual v3',
        type: 'reranker'
      }
    ]
  },
  {
    id: 'jina-reranker',
    name: 'Jina Reranker',
    description: 'Jina AI 重排序模型',
    icon: 'reranker',
    color: 'orange',
    category: 'reranker',
    isConfigured: false,
    models: [
      {
        id: 'jina-reranker-v2-base-multilingual',
        name: 'jina-reranker-v2-base-multilingual',
        displayName: 'Jina Reranker v2 多语言',
        type: 'reranker'
      }
    ]
  }
]
