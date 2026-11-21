# Agent Note: 基础控件的属性与状态契约

Status: implemented

## Problem

Switch 把调用方的 `onClick` 留在最后展开的 props 中，覆盖了内部组合处理，导致该组合不再切换。TagInput 在追加后才检查数量，已有标签达到上限时仍能多加一项。SearchInput 的输入框被禁用或只读后，清空按钮仍能修改值。IconButton 的 `asChild` 分支给 Slot 传入两个同级子节点，违反单子节点约束。Progress 只把 value 用于样式，没有交给 Radix，且自定义 max 与可见比例不一致。

## Decision

Switch 明确取出 `onClick`，在内部先调用一次，并保留 `defaultPrevented`、受控状态和 disabled 规则。

TagInput 的 `appendTagText` 只计算本次新输入，不改写调用方已存标签。Enter、失焦、添加按钮与粘贴复用它，先检查数量；零上限保留无限制语义，长度按 Unicode 码点计算。拒绝的片段留在输入框，粘贴保留原有未添加文字，输入法组合期的确认 Enter 不触发添加。

尚未添加的非空文字通过原生 `setCustomValidity` 阻止外层提交，即使删除旧标签腾位后已经能添加，也要明确添加或清空后再保存。文档保存、证据集创建和难例转换都使用真实 form 提交；后两个按钮通过原生 `form` 属性关联各自标签表单，转换通过实际 submitter 的 value/name 传递反馈和问题身份，不另存最后点击对象或一份可提交状态。文档存量标签与异步保存的合同见[文档标签读写](2026-11-16-document-tag-save-contract.md)。

SearchInput 把 disabled／readOnly 同时交给原生输入框及清空动作；可编辑时仍按原顺序修改值、调用 onClear 并恢复焦点。IconButton 的 Slot 分支直接传入调用方的单个子元素，沿用原 aria-label／title；原生按钮继续保留隐藏标签和默认非提交类型。

Progress 将原 value／max 传给 Radix Root，保留 SDK 的 ARIA、范围回退和错误诊断。指示条仅为比例计算采用与已安装 Radix 1.1.8 相同的范围规则。未设置值时仍是不确定进度。共享组件的类名、原生属性类型、ref 包装及其余 Radix 组合保持。

## Alternatives considered

- 在各页面绕过组合点击或限制追加，可以修复个别入口，但其他控件调用与 Enter／失焦／粘贴仍会走原路径，因此修复控件本身的事件和追加所有者。
- 给 Slot 添加外层 DOM 可以容纳两个子节点，但会改变原生链接、点击和焦点边界。直接保留被插槽的元素及其自身标签属性，不增加包装元素。
- 只给 Progress 的 DOM 手写 aria-valuenow 可暴露当前数字，但会绕过 Radix 的 max、不确定状态与诊断。把原始属性继续交给 Radix，视觉比例与其规则保持一致。

## Consequences

公共控件值、类型、默认尺寸和视觉方向不变；问题属性组合恢复其已声明的行为。StatusBadge 仍显示原有状态点，退出未被读取的私有图标数据；showIcon 可选属性为原兼容表面保留，不借本次改造增加图标或重设计。Badge 仅采用项目选定的直接具名导出。

DOM 回归运行真实 React、控件、Radix 和翻译 Provider，只合成用户输入事件；原控件缺陷覆盖所有追加入口、受控／禁用与默认阻止、Slot 链接、进度范围和清空焦点。标签补充检查覆盖拒绝文字保留、部分批次、粘贴、组合输入、Unicode 以及腾位后未添加文字不会被外层保存丢弃。Edge 从真实文档详情、证据集创建与难例转换入口验证原生表单、失败保留和成功读回，视口为 1440×900、390×844；接口使用 HTTP fixture，未启动后端、解析器或模型。详细范围和结果归档在本批 tag-input 任务目录，不把这些检查外推为其他控件页面的完整验收。
