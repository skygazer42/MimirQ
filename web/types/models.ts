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
    description: 'GPT-5.4 系列旗舰模型',
    icon: 'openai',
    color: 'emerald',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'gpt-5.4',
        name: 'gpt-5.4',
        displayName: 'GPT-5.4',
        type: 'chat',
        contextWindow: 128000,
        maxTokens: 32768,
      },
      {
        id: 'gpt-5.4-thinking',
        name: 'gpt-5.4-thinking',
        displayName: 'GPT-5.4 Thinking',
        type: 'chat',
        contextWindow: 128000,
        maxTokens: 32768,
      },
      {
        id: 'gpt-5.4-pro',
        name: 'gpt-5.4-pro',
        displayName: 'GPT-5.4 Pro',
        type: 'chat',
        contextWindow: 256000,
        maxTokens: 65536,
      },
      {
        id: 'gpt-5.4-mini',
        name: 'gpt-5.4-mini',
        displayName: 'GPT-5.4 mini',
        type: 'chat',
        contextWindow: 128000,
        maxTokens: 16384,
      },
      {
        id: 'gpt-5.4-nano',
        name: 'gpt-5.4-nano',
        displayName: 'GPT-5.4 nano',
        type: 'chat',
        contextWindow: 64000,
        maxTokens: 8192,
      },
      {
        id: 'gpt-5.3-instant',
        name: 'gpt-5.3-instant',
        displayName: 'GPT-5.3 Instant',
        type: 'chat',
        contextWindow: 64000,
        maxTokens: 8192,
      }
    ]
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    description: 'Claude 4 系列模型',
    icon: 'anthropic',
    color: 'orange',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'claude-opus-4.6',
        name: 'claude-opus-4.6',
        displayName: 'Claude Opus 4.6',
        type: 'chat',
        contextWindow: 200000,
      },
      {
        id: 'claude-sonnet-4.6',
        name: 'claude-sonnet-4.6',
        displayName: 'Claude Sonnet 4.6',
        type: 'chat',
        contextWindow: 200000,
      },
      {
        id: 'claude-haiku-4.5',
        name: 'claude-haiku-4.5',
        displayName: 'Claude Haiku 4.5',
        type: 'chat',
        contextWindow: 200000,
      }
    ]
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    description: 'DeepSeek-V3 系列模型',
    icon: 'deepseek',
    color: 'blue',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'deepseek-v3.2',
        name: 'deepseek-v3.2',
        displayName: 'DeepSeek-V3.2',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'deepseek-v3.2-speciale',
        name: 'deepseek-v3.2-speciale',
        displayName: 'DeepSeek-V3.2-Speciale',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'deepseek-r1-r2',
        name: 'deepseek-r1-r2',
        displayName: 'DeepSeek-R1/R2',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'deepseek-coder-v3',
        name: 'deepseek-coder-v3',
        displayName: 'DeepSeek-Coder-V3',
        type: 'chat',
        contextWindow: 128000,
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
    description: 'Qwen3 系列模型',
    icon: 'qwen',
    color: 'sky',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'qwen3.6-plus',
        name: 'qwen3.6-plus',
        displayName: 'Qwen3.6-Plus',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'qwen3-max',
        name: 'qwen3-max',
        displayName: 'Qwen3-Max',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'qwen3.5-flash',
        name: 'qwen3.5-flash',
        displayName: 'Qwen3.5-Flash',
        type: 'chat',
        contextWindow: 64000,
      },
      {
        id: 'qwen3-omni',
        name: 'qwen3-omni',
        displayName: 'Qwen3-Omni',
        type: 'image',
        contextWindow: 128000,
      },
      {
        id: 'qwen3-coder',
        name: 'qwen3-coder',
        displayName: 'Qwen3-Coder',
        type: 'chat',
        contextWindow: 128000,
      }
    ]
  },
  {
    id: 'moonshot',
    name: 'Moonshot AI',
    description: 'Kimi K2 系列模型',
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
        contextWindow: 200000,
      },
      {
        id: 'kimi-k2',
        name: 'kimi-k2',
        displayName: 'Kimi K2',
        type: 'chat',
        contextWindow: 200000,
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
    description: 'Doubao-Seed 系列模型',
    icon: 'ark',
    color: 'orange',
    category: 'model',
    isConfigured: false,
    models: [
      {
        id: 'doubao-seed-2.0-pro',
        name: 'doubao-seed-2.0-pro',
        displayName: 'Doubao-Seed-2.0 Pro',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'doubao-seed-2.0-lite',
        name: 'doubao-seed-2.0-lite',
        displayName: 'Doubao-Seed-2.0 Lite',
        type: 'chat',
        contextWindow: 128000,
      },
      {
        id: 'doubao-seed-2.0-mini',
        name: 'doubao-seed-2.0-mini',
        displayName: 'Doubao-Seed-2.0 Mini',
        type: 'chat',
        contextWindow: 64000,
      },
      {
        id: 'doubao-seedance-2.0',
        name: 'doubao-seedance-2.0',
        displayName: 'Doubao-Seedance-2.0',
        type: 'image',
        contextWindow: 64000,
      },
      {
        id: 'seedream-5.0',
        name: 'seedream-5.0',
        displayName: 'Seedream-5.0',
        type: 'image',
        contextWindow: 64000,
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
        id: 'deepseek-v3.2-sf',
        name: 'deepseek-v3.2',
        displayName: 'DeepSeek-V3.2',
        type: 'chat',
        contextWindow: 128000,
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
        id: 'gpt-5.4-or',
        name: 'openai/gpt-5.4',
        displayName: 'GPT-5.4',
        type: 'chat',
        contextWindow: 128000
      },
      {
        id: 'claude-opus-4.6-or',
        name: 'anthropic/claude-opus-4.6',
        displayName: 'Claude Opus 4.6',
        type: 'chat',
        contextWindow: 200000
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
