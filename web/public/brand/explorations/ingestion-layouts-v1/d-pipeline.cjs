const { facts, esc, icon, file, button, select, header, submit, write } = require('./parts.cjs')

const css = `
.pipeline-workspace{height:852px;flex:none;display:flex;flex-direction:column;padding:0 28px;background:var(--surface)}
.pipeline-context{height:111px;flex:none;display:flex;align-items:center;gap:36px;border-bottom:1px solid var(--line)}.target-dataset{width:226px;flex:none}.target-dataset .field-label{margin-bottom:5px}.target-dataset .select{height:38px}.endpoint{flex:1;min-width:0}.endpoint>.field-label{margin-bottom:6px}.endpoint-options{display:grid;grid-template-columns:repeat(3,1fr);gap:0;border:1px solid var(--line);border-radius:6px;overflow:hidden;background:var(--white)}.endpoint-option{height:47px;padding:0 15px;display:flex;align-items:center;gap:10px;border-right:1px solid var(--line);font-size:13px}.endpoint-option:last-child{border-right:0}.endpoint-option.selected{background:var(--selected);box-shadow:inset 0 -2px 0 var(--ink)}.endpoint-option .radio{margin-top:0;width:14px;height:14px}.endpoint-option strong{font-size:13px;white-space:nowrap}.endpoint-option small{font-size:11px;color:var(--muted);white-space:nowrap;margin-left:auto}
.pipeline-columns{display:grid;grid-template-columns:370px 330px 285px 295px;flex:1;min-height:0;padding-top:26px}.pipeline-stage{min-width:0;display:flex;flex-direction:column;border-right:1px solid var(--line);padding:0 23px}.pipeline-stage:first-child{padding-left:0}.pipeline-stage:last-child{border:0;padding-right:0}.stage-heading{height:73px;flex:none;border-top:3px solid var(--ink);padding-top:13px;position:relative}.stage-heading:after{content:'';position:absolute;right:-34px;top:23px;width:19px;height:19px;background:var(--surface);z-index:1}.stage-arrow{position:absolute;right:-34px;top:23px;z-index:2;color:var(--muted)}.stage-arrow .icon{width:17px;height:17px}.stage-heading .heading-line{display:flex;align-items:center;gap:12px}.stage-index{font-size:12px;letter-spacing:1px;color:var(--muted);font-weight:600;font-variant-numeric:tabular-nums}.stage-heading h2{font-size:17px;line-height:24px;font-weight:650}.stage-heading p{padding-left:31px;margin-top:4px;font-size:12px;color:var(--muted)}.stage-content{flex:1;min-height:0;display:flex;flex-direction:column}.stage-end{height:76px;flex:none;padding-top:14px;border-top:1px solid var(--line);font-size:12px;color:var(--muted);line-height:21px}.stage-end strong{display:block;font-size:12px;color:var(--ink);font-weight:550}.stage-heading .phase-state{margin-left:auto;color:var(--muted);font-size:11px;white-space:nowrap}.pipeline-stage.idle .stage-heading{border-top-color:#C9D1D8}.pipeline-stage.idle .stage-heading h2{color:var(--muted)}.pipeline-stage.idle .stage-index{color:var(--muted)}.pipeline-stage.idle .stage-heading p{color:var(--muted)}.pipeline-stage.idle .stage-content{color:var(--muted)}.pipeline-stage.idle .stage-end strong{color:var(--muted)}
.source-line{display:flex;align-items:center;gap:10px;height:38px;margin-bottom:8px;font-size:13px}.source-line>.icon{width:16px;height:16px}.source-line .source-name{font-weight:600}.source-line .source-change{margin-left:auto;font-size:12px;display:flex;align-items:center;gap:5px;color:var(--muted)}.source-change .icon{width:12px;height:12px}.compact-upload{height:65px;display:flex;align-items:center;gap:12px;padding:0 13px;border:1px dashed #BAC4CE;border-radius:5px;background:#F3F5F7;margin-bottom:16px}.compact-upload>.icon{color:var(--muted);width:21px;height:21px}.compact-upload strong{display:block;font-size:12px;font-weight:550}.compact-upload small{display:block;color:var(--muted);font-size:11px;margin-top:1px}.compact-upload .btn{margin-left:auto;height:29px;padding:0 10px;font-size:12px}.file-list-title{height:28px;display:flex;align-items:flex-start;justify-content:space-between;font-size:11px;color:var(--muted)}.file-list-title strong{color:var(--ink);font-size:12px;font-weight:550}.pipeline-file{height:48px;display:flex;align-items:center;gap:10px;border-bottom:1px solid #E3E7EB}.pipeline-file .file-name{flex:1;font-size:12px;gap:9px}.pipeline-file .file-name .icon{width:16px;height:18px}.pipeline-file .file-size{color:var(--muted);font-size:11px;white-space:nowrap;font-variant-numeric:tabular-nums}.file-list-more{height:39px;display:flex;align-items:center;justify-content:center;gap:6px;font-size:12px;color:var(--muted)}.file-list-more .icon{width:13px;height:13px}
.stage-field{padding:17px 0 18px;border-bottom:1px solid var(--line)}.stage-field:first-child{padding-top:9px}.stage-field .field-label{margin-bottom:7px;font-size:12px}.stage-field .select{height:37px}.field-explanation{font-size:12px;line-height:21px;color:var(--muted);margin-top:9px}.parser-formats{display:flex;gap:7px;margin-top:12px;color:var(--muted);font-size:10px;letter-spacing:.2px}.parser-formats span{padding:1px 6px;background:var(--subtle);border-radius:3px}.stage-settings{display:flex;align-items:center;gap:7px;font-size:12px;font-weight:550;height:51px}.stage-settings .icon{width:14px;height:14px}.parse-boundary{margin-top:19px;padding-left:13px;border-left:2px solid #85909B;color:var(--muted);font-size:12px;line-height:22px}.parse-boundary strong{display:block;color:var(--ink);font-size:13px;font-weight:600;margin-bottom:4px}
.idle-intro{font-size:13px;line-height:24px;padding-top:12px;min-height:80px}.idle-intro strong{display:block;font-size:13px;color:var(--muted);font-weight:550;margin-bottom:4px}.idle-intro p{font-size:12px;line-height:22px;color:var(--muted)}.idle-rule{padding:18px 0;border-bottom:1px solid var(--line);display:flex;align-items:flex-start;gap:10px}.idle-rule>.icon{width:17px;height:17px;margin-top:3px;color:#87939E}.idle-rule strong{font-size:12px;font-weight:550;color:var(--muted);display:block}.idle-rule p{font-size:12px;line-height:21px;color:var(--muted);margin-top:4px}.idle-note{font-size:12px;line-height:23px;color:var(--muted);padding:21px 0 16px}.idle-note strong{font-size:12px;font-weight:550;color:var(--muted);display:block;margin-bottom:4px}.idle-link{font-size:12px;font-weight:550;display:flex;align-items:center;gap:6px;color:var(--muted)}.idle-link .icon{width:13px;height:13px}.idle-spacer{flex:1;min-height:16px}.inactive-parameter{display:flex;align-items:center;justify-content:space-between;padding:18px 0;border-bottom:1px solid var(--line);font-size:12px;color:var(--muted)}.inactive-parameter strong{font-size:13px;color:var(--muted);font-weight:500;font-variant-numeric:tabular-nums}.inactive-parameter span small{display:block;font-size:11px;color:var(--muted);margin-top:4px}.index-result{padding-top:21px;font-size:12px;color:var(--muted);line-height:23px}.index-result strong{display:block;color:var(--muted);font-size:12px;font-weight:550;margin-bottom:6px}.result-line{display:flex;gap:8px;align-items:center;margin:5px 0}.result-line .icon{width:14px;height:14px;color:#8A959E}.pipeline-stage.idle .stage-end .text-action{margin-top:5px;color:var(--muted)}.pipeline-stage.idle .stage-end .text-action .icon{width:13px;height:13px}
`

const stageHeader = (number, title, description, active, arrow = true) => `<header class="stage-heading"><div class="heading-line"><span class="stage-index">${number}</span><h2>${title}</h2>${active ? '' : '<span class="phase-state">本次不执行</span>'}</div><p>${description}</p>${arrow ? `<span class="stage-arrow">${icon('arrow-right')}</span>` : ''}</header>`
const files = facts.documents.slice(0, 8).map(doc => `<div class="pipeline-file">${file(doc)}<span class="file-size">${esc(doc.size)}</span></div>`).join('')
const endpointModes = facts.modes.map(mode => `<div class="endpoint-option ${mode.value === facts.executionMode ? 'selected' : ''}"><span class="radio"></span><strong>${esc(mode.label)}</strong><small>${mode.value === 'upload_only' ? '文件' : mode.value === 'parse_only' ? '文件 + 正文' : '可检索'}</small></div>`).join('')

const content = `${header()}
<div class="pipeline-workspace">
  <div class="pipeline-context">
    <div class="target-dataset"><label class="field-label">目标数据集</label>${select(facts.dataset, 'dataset')}</div>
    <div class="endpoint"><label class="field-label">执行终点</label><div class="endpoint-options">${endpointModes}</div></div>
  </div>
  <div class="pipeline-columns">
    <section class="pipeline-stage source-stage">
      ${stageHeader('01', '登记文件', '确认本次要导入的源文件', true)}
      <div class="stage-content">
        <div class="source-line">${icon('upload-cloud')}<span class="source-name">本地文件</span><span class="source-change">更换来源${icon('chevron-down')}</span></div>
        <div class="compact-upload">${icon('upload-cloud')}<div><strong>拖入文件，继续添加</strong><small>单文件最大 ${facts.maxFileSize}</small></div>${button('选择文件')}</div>
        <div class="file-list-title"><strong>待提交文件</strong><span>${facts.documents.length} 份 · ${facts.totalSize}</span></div>
        <div class="pipeline-files">${files}</div>
        <div class="file-list-more">还有 4 个文件${icon('chevron-down')}</div>
        <div class="spacer"></div>
      </div>
      <div class="stage-end"><strong>文件与记录</strong>保存源文件，登记到「产品文档」</div>
    </section>
    <section class="pipeline-stage parsing-stage">
      ${stageHeader('02', '解析正文', '本次执行在这里结束', true)}
      <div class="stage-content">
        <div class="stage-field"><label class="field-label">解析器</label>${select(facts.parser, 'parsing')}<p class="field-explanation">按文件格式选择解析器，提取可阅读的正文。</p><div class="parser-formats"><span>PDF</span><span>Office</span><span>Markdown</span><span>更多格式</span></div></div>
        <div class="stage-field"><label class="field-label">导入方式</label>${select(facts.ingestMode)}<p class="field-explanation">将新文件追加到当前数据集。</p></div>
        <div class="stage-field"><label class="field-label">去重策略</label>${select(facts.dedup)}<p class="field-explanation">通过文件内容识别重复文档。</p></div>
        <div class="stage-settings">${icon('settings2')}解析设置${icon('chevron-down')}</div>
        <div class="parse-boundary"><strong>仅提取并保存正文</strong>本次不会切块、向量化或建立检索索引，解析完成后可继续处理。</div>
        <div class="spacer"></div>
      </div>
      <div class="stage-end"><strong>解析后的正文</strong>可在文档解析中查看处理结果</div>
    </section>
    <section class="pipeline-stage idle governance-stage">
      ${stageHeader('03', '治理', '建立索引前的内容处理', false)}
      <div class="stage-content">
        <div class="idle-intro"><strong>使用已有治理配置</strong><p>完整入库时按平台配置处理正文。</p></div>
        <div class="idle-rule">${icon('data-governance')}<div><strong>清洗与规范</strong><p>清理无效内容，统一文本格式。</p></div></div>
        <div class="idle-rule">${icon('rule-set')}<div><strong>脱敏与质量规则</strong><p>按治理配置检查内容与敏感信息。</p></div></div>
        <div class="idle-note"><strong>本次保留解析正文</strong>执行终点为「入库并解析」，不会继续进入后续处理阶段。</div>
        <div class="idle-link">查看治理配置${icon('arrow-up-right')}</div>
        <div class="idle-spacer"></div>
      </div>
      <div class="stage-end"><strong>需要执行后续处理？</strong><span class="text-action">切换为「解析 + 索引」${icon('arrow-up-right')}</span></div>
    </section>
    <section class="pipeline-stage idle index-stage">
      ${stageHeader('04', '建索引', '让文档进入知识库检索', false, false)}
      <div class="stage-content">
        <div class="idle-intro"><strong>切块、向量化与检索索引</strong><p>选择「解析 + 索引」时使用。</p></div>
        <div class="inactive-parameter"><span>切块大小<small>每个文本片段的长度</small></span><strong>${facts.chunkSize}</strong></div>
        <div class="inactive-parameter"><span>重叠长度<small>相邻片段保留的上下文</small></span><strong>${facts.chunkOverlap}</strong></div>
        <div class="index-result"><strong>进入检索的内容</strong><div class="result-line">${icon('chunking')}文档切块</div><div class="result-line">${icon('database')}向量与关键词索引</div></div>
        <div class="idle-note">模型与召回参数沿用设置页配置，无需在这里重复设置。</div>
        <div class="idle-spacer"></div>
      </div>
      <div class="stage-end"><strong>本次不建立索引</strong>当前文件不会进入知识库检索</div>
    </section>
  </div>
</div>
${submit()}`

write('d-pipeline', 'D · 横向流程', css, content)
