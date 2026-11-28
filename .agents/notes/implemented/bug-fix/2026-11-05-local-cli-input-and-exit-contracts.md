# Agent Note: 本地命令入口的参数与退出状态

Status: implemented

## Problem

两个 PowerShell 开发入口把参数命名为 Host，与 PowerShell 自带的只读自动变量冲突。参数绑定在执行脚本正文之前就报 VariableNotWritable，因此默认或显式 Host 都无法进入启动流程。

verify.ps1 只设置 ErrorActionPreference=Stop，没有检查外部命令的退出码。在文档使用的 Windows PowerShell 中，失败的原生命令仍能执行到末尾的 OK。入库演示的 JSON 提取函数又同时把 Python 程序和管道 JSON 放在 stdin；程序的 here-document 覆盖 JSON 管道。登录和数据集载荷直接拼接文本，也无法保留密码或名称中的引号、反斜杠等合法字符。

## Decision

开发入口使用 BackendHost 局部参数，并把 Host 保留为其命令行别名。参数顺序、默认地址、端口、开关、环境字段和原启动命令保持；不改变开发窗口或服务生命周期。

验证入口逐步检查每个原生命令的 LASTEXITCODE，复用同文件的一个断言函数。任一步失败就停止并报告该步名称和退出码；命令、先后顺序、Skip 开关及最后的 OK 规则保留。现有 audit.ps1 已采用同样的原生命令边界，本批保留其原文。

JSON 提取程序通过 Python -c 提供，把 stdin 留给原管道 JSON；原字段遍历与可空值输出保持。登录与数据集载荷由标准 json.dumps 编码真实字符串，字段、HTTP 路径、认证、上传、轮询和导出流程不变。不增加通用命令管理器、服务包装层或额外依赖。

## Alternatives considered

- 保留 Host 参数并写入脚本级同名变量仍会触及只读自动变量；内部改名加原别名可以保留公开调用。
- 依赖较新 PowerShell 的原生命令错误偏好会改变文档的 Windows PowerShell 要求，因此显式检查已有退出码。
- 把 JSON 管道重新放进另一个 here-document 仍无法同时承载程序与数据，因此使用解释器现有的 -c 接口。
- 手工替换引号和反斜杠容易遗漏控制字符；标准 JSON 编码直接表达实际载荷契约。

## Consequences

本地开发脚本能完成原参数绑定，验证脚本不再把失败标成 OK，演示入口能够读取管道结果并保留字符串内容。原失败会更早显式退出，调用者需要修复该步错误；没有更改项目默认验证范围或取消 Python 测试命令。

基线与修复的参数测试只提取真实 ParamBlock 并执行常量返回正文，没有启动开发脚本。退出状态测试只提取断言函数并运行独立的 Node exit7/exit0 哨兵，没有运行仓库校验命令。PowerShell 与 Bash 只做语法检查，内嵌 Python 只比较 AST 和 stdin 参数连接，不执行 helper、Python 测试、应用、模型、网络或服务。

活跃笔记按 dev_all、dev_backend、verify.ps1、json_get、Host 和原生退出码检索，没有同一决定的历史记录；现有 API／手册工具笔记不承担这些启动入口，不被替代或归档。
