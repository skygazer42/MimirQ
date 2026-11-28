# 全项目过度防御检查

Python 和 TypeScript 检查器遍历项目文件，输出每个文件的发现及其位置。发现是审查候选，不表示应删除所有默认值和异常处理。

在仓库根目录运行 Python 检查：

```powershell
.venv/Scripts/python.exe scripts/audit_defensive_code.py --output artifacts/code-style/python-audit.json
```

在 `web` 目录运行 TypeScript 检查：

```powershell
node scripts/audit-defensive-code.mjs artifacts/code-style/frontend-audit.json
```

两条命令默认只读。Python 使用 Git 跟踪文件和未忽略的新文件作为完整清单，包含测试、工具、配置、文档与资源；依赖、构建产物和历史取证不作为产品源码。TypeScript 检查器使用编译器 AST 和类型信息；静态 JavaScript、HTML 内联脚本和生成文件另行标明分析方式。

Python 规则覆盖：

- 已声明配置字段的 `getattr`、重复类型转换及无作用的默认值。
- `_coerce_*`、`_safe_*`、`_as_*` 辅助函数。
- 宽泛异常捕获、异常后的空结果和布尔默认值。
- 只有基本类型解析的异常处理与实际数据库、网络调用之间的区别。

TypeScript 规则覆盖重复基本类型转换、确定存在值的默认值与可选访问、已知数组的重复验证及异常处理。数组索引、字典键、外部接口、浏览器存储和鉴权边界不能只凭类型断言删除校验。

安全改写仍需检查调用链。Python 的 `--apply-safe --scope app/api --backup artifacts/code-style/before` 仅修改指定范围内已证明的表达式，并在写入前检查并发变化、保存原始编码和换行。`--narrow-primitive-errors` 只收窄由基本类型解析构成的异常处理，不把外部调用失败转换成默认成功。

函数参数来自 JWT、HTTP、模型输出、插件、JSON 或数据库历史字段时，应在入口按契约验证；来自已验证 DTO、ORM 字段或 argparse 类型参数时，应直接使用相应类型。非法必填配置、数据库失败、缺失身份和签名失败必须保持可观察，不能以空数组、默认身份或跳过门禁来掩盖。

全项目审查记录位于 `artifacts/code-style/full-audit-v2/`。其中覆盖表区分自动规则检查、人工调用链复核、已修改和保留候选；不会把自动遍历表述为每条控制流都已人工认证。

## 内部状态与嵌套控制流

后续清理记录位于 `artifacts/code-style/nesting-cleanup-v3/`。这一轮追踪缓存写入者、ORM 查询、Pydantic 后置校验和 CLI 参数，直接使用已确定的类型。例如，认证已经写入的租户 UUID 在请求缓存中直接复用，字符串 UUID 只在输入或序列化边界解析。

完整 Python 控制流检查在仓库根目录运行：

```powershell
.venv/Scripts/python.exe -m scripts.simplify_defensive_control_flow --output artifacts/code-style/control-flow.json
```

该命令默认只读。它识别没有替代分支的连续条件、退出语句后的多余 `else`，以及需要追踪输入来源的保护性重解析。适用的结构改写会先验证规范化 AST 一致，保留短路顺序、字符串内容和作用域；需要写入时明确指定 `--apply --scope app/api --backup artifacts/code-style/control-flow-before`。

原生 UUID、已验证模型字段及内部缓存值不需要再次按未知数据解析。HTTP、JSON、Redis、插件和环境配置仍在真实边界处理格式与缺失值；缓存缺失和合法的空字典、空集合分别按契约处理。
