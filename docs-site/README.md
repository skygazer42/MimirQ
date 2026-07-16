# MimirQ 全栈手册（Docusaurus）

本目录为 [MimirQ](https://github.com/skygazer42/MimirQ) 的 **docs-site**：与 `docs/api/site` 的 Redoc **并存**，部署在 GitHub Pages 的 **`/MimirQ/handbook/`** 路径下。

## 本地开发

```bash
cd docs-site
npm ci
npm run start
```

浏览器访问：`http://localhost:3000/MimirQ/handbook/`（与 `docusaurus.config.ts` 中 `baseUrl` 一致）。

## 构建与合并到 Pages 产物

```bash
# 仓库根目录：需先有 web/openapi.json（make openapi-export）
make handbook-build
# 输出：docs/api/site/handbook/
```

或仅构建站点（不拷贝）：

```bash
cd docs-site && npm run build
```

## 脚本

- 生成样板 Markdown：`python ../scripts/docs/bootstrap_handbook.py`（覆盖式，慎用；**手册正文以 Git 为准**）
- 生成 FE/BE 矩阵：`python ../scripts/docs/generate_fe_be_matrix.py`
- 矩阵与仓库一致：`make handbook-matrix-check`（再生成后 `git diff` 必须为干净）
- 相对链接检查：`npm run check:links`

## 国际化

- 默认语言：`zh-Hans`
- `en`：构建前由 `scripts/docs/sync-handbook-i18n.mjs` 镜像文档，并以 `i18n/en-overrides/current/` 覆盖英文欢迎页等。
