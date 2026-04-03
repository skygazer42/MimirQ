---
sidebar_label: "分页"
sidebar_position: 4
---

# 分页模式

MimirQ 列表接口采用 offset/limit 分页模式，部分接口可能支持 cursor 分页。

## 基本参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `skip` / `offset` | int | `0` | 跳过的记录数 |
| `limit` | int | `20` | 每页返回数量 |

:::info
参数名以 [Redoc](https://skygazer42.github.io/MimirQ/) 中各接口的实际定义为准，部分接口使用 `skip`，部分使用 `offset`。
:::

## Offset/Limit 分页

```bash
# 第一页
curl "$BASE_URL/api/v1/datasets/?skip=0&limit=20" \
  -H "Authorization: Bearer $TOKEN"

# 第二页
curl "$BASE_URL/api/v1/datasets/?skip=20&limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

典型响应结构：

```json
{
  "items": [...],
  "total": 150,
  "skip": 0,
  "limit": 20
}
```

## 分页最佳实践

### 固定排序键

```bash
# 带排序的分页，避免数据变动导致重复或遗漏
curl "$BASE_URL/api/v1/documents/?skip=0&limit=50&sort_by=created_at&order=desc" \
  -H "Authorization: Bearer $TOKEN"
```

:::warning 并发写入时的分页
在数据频繁变动的场景下，offset 分页可能出现重复或遗漏记录。建议固定排序键（如 `created_at`），或在批处理脚本中使用时间窗口过滤。
:::

### 边界处理

| 场景 | 预期行为 |
|------|----------|
| `skip` 超过总数 | 返回空 `items`，`total` 不变 |
| `limit` 超过上限 | 返回 422 或被截断为最大值 |
| `limit=0` | 以 OpenAPI 定义为准 |
| 空列表 | `items: []`，`total: 0` |

## 集成建议

- **前端翻页**：URL 中保留完整查询参数（包括 `limit`），支持深链分享
- **导出脚本**：设置合理的 `limit`（如 100），循环翻页直到 `items` 为空
- **大 limit 警告**：过大的 `limit` 值可能导致响应缓慢或 422，以 Redoc 中标注的上限为准

```python
# Python 分页遍历示例
skip = 0
limit = 100
while True:
    resp = requests.get(
        f"{BASE_URL}/api/v1/datasets/",
        params={"skip": skip, "limit": limit},
        headers={"Authorization": f"Bearer {token}"}
    )
    data = resp.json()
    process(data["items"])
    if len(data["items"]) < limit:
        break
    skip += limit
```

## 相关链接

- [Redoc — API 完整参考](https://skygazer42.github.io/MimirQ/)
- [错误码与响应体](./errors-4xx-5xx.md) — 分页参数错误时的 422 响应
