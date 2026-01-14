# MimirQ API 接口文档

> 本文档面向开发者，帮助你快速接入 MimirQ 知识库问答系统。

---

## 目录

1. [快速入门](#快速入门)
2. [核心使用流程](#核心使用流程)
3. [完整代码示例](#完整代码示例)
4. [API 详细参考](#api-详细参考)
5. [常见问题解答](#常见问题解答)

---

# 快速入门

## 这是什么？

MimirQ 是一个 **RAG（检索增强生成）知识库问答系统**。简单来说：

1. 你上传文档（PDF、Word、Markdown 等）
2. 系统自动解析、分块、向量化存储
3. 用户提问时，系统检索相关内容，结合 AI 生成答案

## 环境准备

### 基础信息

| 项目 | 值 |
|------|-----|
| Base URL | `http://localhost:8000/api/v1` |
| 数据格式 | JSON |
| 流式响应 | SSE (Server-Sent Events) |

### 你需要准备

1. **后端服务运行中** - 确保 MimirQ 后端已启动
2. **HTTP 客户端** - 如 Postman、curl、或你的代码
3. **认证信息** - 用户账号或 API Token

---

## 认证方式（二选一）

### 方式一：JWT Token（推荐）

先登录获取 token，然后在请求头中携带：

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### 方式二：Header 模式（开发调试用）

直接在请求头中传入用户和租户信息：

```
X-User-ID: your-account-id
X-Tenant-ID: your-tenant-id
```

---

## 5 分钟快速体验

### 第 1 步：注册账号

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "username": "testuser",
    "password": "password123"
  }'
```

**返回示例：**
```json
{
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "test@example.com",
    "username": "testuser"
  },
  "token": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "expires_in": 3600
  }
}
```

> 保存 `access_token`，后续请求都需要用到！

### 第 2 步：上传文档

```bash
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/your/document.pdf"
```

**返回示例：**
```json
{
  "id": "doc-uuid-12345",
  "filename": "document.pdf",
  "status": "pending",
  "processing_progress": 0
}
```

> 文档会在后台自动处理，状态从 `pending` → `processing` → `completed`

### 第 3 步：检查文档状态

```bash
curl http://localhost:8000/api/v1/documents/doc-uuid-12345/status \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**返回示例：**
```json
{
  "id": "doc-uuid-12345",
  "status": "completed",
  "processing_progress": 100,
  "current_stage": "done"
}
```

### 第 4 步：开始对话！

```bash
curl -X POST http://localhost:8000/api/v1/chat/stream \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "这份文档主要讲了什么？",
    "document_ids": ["doc-uuid-12345"],
    "stream": true
  }'
```

**返回（SSE 流式）：**
```
data: {"type": "citations", "data": [...]}

data: {"type": "token", "data": {"content": "这份"}}

data: {"type": "token", "data": {"content": "文档"}}

data: {"type": "token", "data": {"content": "主要"}}

...

data: {"type": "done", "data": {"conversation_id": "conv-uuid", "total_tokens": 150}}
```

恭喜！你已经完成了基本的接入流程！

---

# 核心使用流程

## 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        你的应用程序                               │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     MimirQ API 网关                              │
│                  http://localhost:8000/api/v1                   │
└─────────────────────────────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│   文档管理     │      │   对话问答     │      │   知识图谱     │
│  /documents   │      │    /chat      │      │     /kg       │
└───────────────┘      └───────────────┘      └───────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                        存储层                                    │
│   PostgreSQL (元数据)  │  Milvus (向量)  │  MinIO (文件)         │
└─────────────────────────────────────────────────────────────────┘
```

## 典型使用场景

### 场景 1：构建企业知识库问答

```
用户 ──► 上传公司文档 ──► 系统处理 ──► 员工提问 ──► AI 回答 + 引用来源
```

**步骤：**
1. 创建数据集（可选，用于分类管理）
2. 批量上传文档
3. 等待处理完成
4. 调用对话接口

### 场景 2：文档智能分析

```
用户 ──► 上传报告 ──► 提取关键信息 ──► 生成摘要/FAQ
```

**步骤：**
1. 上传文档
2. 使用结构化输出功能
3. 获取 JSON 格式的分析结果

