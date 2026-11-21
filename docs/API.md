# Ragvia API 文档索引

> **SSOT 提示**：接口字段以 OpenAPI（`web/openapi.json`）与 [在线 Redoc](https://skygazer42.github.io/MimirQ/) 为准。以下为导航入口；长篇叙述已按一级标题拆分为多文件。

## 在线资源

| 资源 | 链接 |
| --- | --- |
| 全栈手册（Docusaurus，可搜索） | [https://skygazer42.github.io/MimirQ/handbook/](https://skygazer42.github.io/MimirQ/handbook/) |
| 全量 OpenAPI / Redoc | [https://skygazer42.github.io/MimirQ/](https://skygazer42.github.io/MimirQ/) |

## 仓库内拆分文档

长篇叙述的正文保存在 **`docs/api/source/legacy-api-narrative.md`**（与历史 `docs/API.md` 等价），并由脚本切分为 **`docs/api/reference/`** 下的多篇 Markdown；入口见 **[分片索引](./api/reference/_index.md)**。

## 集成与排障

- [API 契约与约定](./integration/API_CONTRACT.md)
- [前后端联调排障](./integration/FE_BE_DEBUG.md)
- [API 导览](./api/README.md) · [场景工作流](./api/workflows.md)

## 维护说明

更新长篇叙述时，优先编辑 **`docs/api/source/legacy-api-narrative.md`**，然后运行：

```bash
python scripts/docs/split_api_md.py
```

也可直接改 `docs/api/reference/` 下单篇（与 legacy 再同步时需人工对齐）。

手册站与对照矩阵：

```bash
python scripts/docs/bootstrap_handbook.py   # 重置样板内容（慎用覆盖）
python scripts/docs/generate_fe_be_matrix.py
cd docs-site && npm run build
```
