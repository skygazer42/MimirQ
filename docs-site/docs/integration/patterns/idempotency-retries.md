---
sidebar_label: "重试 / 幂等"
sidebar_position: 7
---

# 重试与幂等

正确的重试策略避免数据脏污和雪崩，幂等设计确保重复请求不产生副作用。

## HTTP 方法幂等性

| 方法 | 幂等 | 安全重试 | 说明 |
|------|------|----------|------|
| GET | 是 | 是 | 只读操作，任意重试 |
| PUT | 是 | 是 | 整体覆盖，结果一致 |
| DELETE | 是 | 是 | 重复删除返回 404 |
| PATCH | 否 | 视情况 | 增量更新可能叠加 |
| POST | 否 | **不安全** | 可能创建重复资源 |

:::warning 非幂等 POST
MimirQ 中创建数据集、上传文档等 POST 操作**默认非幂等**。网络超时后盲目重试可能导致重复资源。
:::

## 幂等键（Idempotency-Key）

对于需要安全重试的 POST 请求，如果 API 支持幂等键：

```bash
curl -X POST "$BASE_URL/api/v1/datasets/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"name": "my-dataset"}'
```

:::info
幂等键支持以 [Redoc](https://skygazer42.github.io/MimirQ/) 中各接口的具体说明为准。并非所有 POST 接口都支持幂等键。
:::

## 指数退避策略

当收到 429（限流）或 503（服务不可用）时，使用指数退避重试：

```python
import time
import random

def retry_with_backoff(func, max_retries=5, base_delay=1.0):
    for attempt in range(max_retries):
        try:
            return func()
        except RetryableError:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            delay = min(delay, 60)  # 最大 60 秒
            time.sleep(delay)
```

### 退避参数建议

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| 基础延迟 | 1 秒 | 首次重试等待 |
| 退避倍数 | 2x | 每次翻倍 |
| 抖动 | 0-1 秒随机 | 避免多客户端同步重试 |
| 最大延迟 | 60 秒 | 退避上限 |
| 最大重试次数 | 3-5 次 | 超过后放弃并报错 |

## 重试决策矩阵

| 状态码 | 重试? | 策略 |
|--------|-------|------|
| 401 | 刷新 Token 后重试一次 | Token 刷新失败则放弃 |
| 409 | 获取最新资源后决定 | 可能需要业务层合并 |
| 429 | 是 | 使用 `Retry-After` Header 或指数退避 |
| 500 | 仅幂等操作 | 非幂等操作记录 request_id 并人工处理 |
| 502/503 | 是 | 指数退避 |

## UI 防重复提交

前端应在以下场景防止重复操作：

- **提交按钮** — loading 状态下禁用点击
- **表单重复提交** — 请求进行中屏蔽二次提交
- **页面刷新** — POST 完成后重定向（PRG 模式），避免浏览器刷新重提

## 相关链接

- [Redoc — API 完整参考](https://skygazer42.github.io/MimirQ/)
- [错误码与响应体](./errors-4xx-5xx.md) | [SSE 流式](./sse-streaming.md)
