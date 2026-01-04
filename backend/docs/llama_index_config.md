# LlamaIndex 分块配置说明

## 配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `LLAMA_INDEX_ENABLED` | 是否启用 LlamaIndex 分块策略 | `false` |

## 如何启用

### 方式一：修改 `.env` 文件

在 `.env` 文件中添加以下配置：

```bash
# 启用 LlamaIndex 分块（默认为 false，需要手动启用）
LLAMA_INDEX_ENABLED=true
```

### 方式二：修改环境变量（不推荐生产环境）

```bash
export LLAMA_INDEX_ENABLED=true
```

## 注意事项

1. **依赖要求**：
   - 需要在 `requirements.txt` 中添加 `llama-index-core>=0.10.0`（已完成）
   - 确保 Python 3.11+ 环境

2. **功能说明**：
   - LlamaIndex 提供两种分块策略：
     - **llama_index**：基于 LlamaIndex SentenceSplitter 的句级分割
     - **llama_index_hierarchical**：基于 HierarchicalNodeParser 的多层结构分块
   - 目前由于 `llama-index-core` 依赖存在编译问题，这两个策略都被禁用

3. **与 LangChain 递归分块的关系**：
   - 默认策略 `langchain_recursive` 已提供良好的递归分块能力
   - LlamaIndex 主要用于需要更精细控制或特定分块需求的场景

4. **前端配置**：
   - 前端在分块策略选择时会检查 `LLAMA_INDEX_ENABLED` 配置
   - 当 `LLAMA_INDEX_ENABLED=false` 时，LlamaIndex 相关选项在前端会被隐藏

