# LlamaIndex 分块配置说明

## 配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `LLAMA_INDEX_ENABLED` | 是否启用 LlamaIndex 分块策略 | `false` |

## 如何启用

在 `.env` 文件中添加：

```bash
# 启用 LlamaIndex 分块（默认为 false，需要手动启用）
LLAMA_INDEX_ENABLED=true
```

## 功能说明

LlamaIndex 提供两种分块策略（已在 chunking factory 注册）：

- **llama_index**：基于 LlamaIndex SentenceSplitter 的句级分割
- **llama_index_hierarchical**：基于 HierarchicalNodeParser 的多层结构分块

依赖与开关：

1. **依赖已内置**：`llama-index-core` 已固定在 `requirements.txt`（当前 `0.14.20`），随后端依赖一起安装，无需单独处理。
2. **默认运行时禁用**：`LLAMA_INDEX_ENABLED=false` 时选择这两个策略会返回明确错误（`app/rag/chunking/factory.py` 的运行时开关），设为 `true` 后即可使用。

## 与 LangChain 递归分块的关系

- 默认策略 `langchain_recursive` 已提供良好的递归分块能力
- LlamaIndex 主要用于需要更精细控制或特定分块需求的场景

## 前端配置

- 前端在分块策略选择时会检查 `LLAMA_INDEX_ENABLED` 配置（`web/lib/chunk-strategies.ts` 将两者列为可选策略）
- 当 `LLAMA_INDEX_ENABLED=false` 时，LlamaIndex 相关选项在前端会被隐藏
