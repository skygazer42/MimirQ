# Agent Note: 基础控件的属性与状态契约

Status: implemented

## Problem

Switch 把调用方的 `onClick` 留在最后展开的 props 中，覆盖了内部组合处理，导致该组合不再切换。TagInput 在追加后才检查数量，已有标签达到上限时仍能多加一项。SearchInput 的输入框被禁用或只读后，清空按钮仍能修改值。IconButton 的 `asChild` 分支给 Slot 传入两个同级子节点，违反单子节点约束。Progress 只把 value 用于样式，没有交给 Radix，且自定义 max 与可见比例不一致。

## Decision

Switch 明确取出 `onClick`，在内部先调用一次，并保留 `defaultPrevented`、受控状态和 disabled 规则。TagInput 在共享追加循环中先检查现有数量；Enter、失焦、添加按钮与粘贴沿用同一所有者，不裁掉已有超限值，零上限仍保留原无限制语义。

SearchInput 把 disabled／readOnly 同时交给原生输入框及清空动作；可编辑时仍按原顺序修改值、调用 onClear 并恢复焦点。IconButton 的 Slot 分支直接传入调用方的单个子元素，沿用原 aria-label／title；原生按钮继续保留隐藏标签和默认非提交类型。

Progress 将原 value／max 传给 Radix Root，保留 SDK 的 ARIA、范围回退和错误诊断。指示条仅为比例计算采用与已安装 Radix 1.1.8 相同的范围规则。未设置值时仍是不确定进度。共享组件的类名、原生属性类型、ref 包装及其余 Radix 组合保持。

## Alternatives considered

- 在各页面绕过组合点击或限制追加，可以修复个别入口，但其他控件调用与 Enter／失焦／粘贴仍会走原路径，因此修复控件本身的事件和追加所有者。
- 给 Slot 添加外层 DOM 可以容纳两个子节点，但会改变原生链接、点击和焦点边界。直接保留被插槽的元素及其自身标签属性，不增加包装元素。
- 只给 Progress 的 DOM 手写 aria-valuenow 可暴露当前数字，但会绕过 Radix 的 max、不确定状态与诊断。把原始属性继续交给 Radix，视觉比例与其规则保持一致。

## Consequences

公共控件值、类型、默认尺寸和视觉方向不变；问题属性组合恢复其已声明的行为。StatusBadge 仍显示原有状态点，退出未被读取的私有图标数据；showIcon 可选属性为原兼容表面保留，不借本次改造增加图标或重设计。Badge 仅采用项目选定的直接具名导出。

DOM 回归运行真实 React、控件、Radix 和翻译 Provider，只合成用户输入事件；原代码出现十二个失败和六个通过，修复后覆盖所有追加入口、受控／禁用与默认阻止、Slot 链接、进度范围和清空焦点。调用清单区分实际页面用法与当前尚无页面使用的公开属性组合。未运行浏览器或应用服务，不能据此宣称页面布局和真实键盘流程已验收。
