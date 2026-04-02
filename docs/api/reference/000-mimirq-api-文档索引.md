# MimirQ API 文档索引

> **SSOT 提示**：接口字段以 OpenAPI（`web/openapi.json`）与 [在线 Redoc](https://skygazer42.github.io/MimirQ/) 为准。以下为导航入口；长篇叙述已按一级标题拆分为多文件。

## 在线资源

| 资源 | 链接 |
| --- | --- |
| 全栈手册（Docusaurus，可搜索） | [https://skygazer42.github.io/MimirQ/handbook/](https://skygazer42.github.io/MimirQ/handbook/) |
| 全量 OpenAPI / Redoc | [https://skygazer42.github.io/MimirQ/](https://skygazer42.github.io/MimirQ/) |

## 仓库内拆分文档

原 `docs/API.md` 全文已切分为 **`docs/api/reference/`** 下的多篇 Markdown，并生成 **[分片索引](./api/reference/_index.md)**。按主题浏览请从索引中的表格进入对应文件。

## 集成与排障

- [API 契约与约定](./integration/API_CONTRACT.md)
- [前后端联调排障](./integration/FE_BE_DEBUG.md)
- [API 导览](./api/README.md) · [场景工作流](./api/workflows.md)

## 维护说明

更新长篇 API 叙述时，可编辑 `docs/api/reference/` 下分片，或改回单文件流程后重新运行：

```bash
python scripts/docs/split_api_md.py
```

手册站与对照矩阵：

```bash
python scripts/docs/bootstrap_handbook.py   # 重置样板内容（慎用覆盖）
python scripts/docs/generate_fe_be_matrix.py
cd docs-site && npm run build
```
