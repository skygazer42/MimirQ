const governanceMessages = {
DataGovernancePage: {
    loading: {
      message: '正在加载数据治理面板...',
      srMessage: 'Loading data governance panel',
    },
  },
GovernanceProfilesRoutePage: {
    loading: {
      message: '正在加载治理 Profiles...',
      srMessage: 'Loading governance profiles page',
    },
  },
GovernanceCommonLinesRoutePage: {
    loading: {
      message: '正在加载样板行发现...',
      srMessage: 'Loading common lines learning page',
    },
  },
DataAnnotator: {
    header: {
      title: '数据标注',
    },
    sections: {
      typeSelector: '选择标注类型',
      existing: '已有标注 ({count})',
    },
    types: {
      entity: {
        label: '实体',
        description: '命名实体，例如人名、地名、组织',
      },
      keyword: {
        label: '关键词',
        description: '重要关键词与高频术语',
      },
      sensitive: {
        label: '敏感信息',
        description: '需要脱敏或重点审查的信息',
      },
      custom: {
        label: '自定义',
        description: '按当前治理规则补充自定义标签',
      },
    },
    counts: {
      typeCount: '{count} 个',
    },
    custom: {
      placeholder: '输入自定义标签名称...',
    },
    selection: {
      title: '已选中文本',
      add: '添加 {label} 标注',
      cancel: '取消',
      start: '开始选中文本标注',
      activePrompt: '请在右侧选中文本...',
    },
    auto: {
      action: 'AI 自动打标',
      running: '正在自动打标...',
      providerTitle: '打标方式',
      providers: {
        cpu: {
          label: '本地轻量',
          description: '关键词、动作项、风险线索，零模型成本',
        },
        llm: {
          label: 'AI 语义',
          description: '摘要、主题、分类与重点短句',
        },
        compliance: {
          label: '敏感合规',
          description: 'PII、密钥和实体线索优先',
        },
        hybrid: {
          label: '混合增强',
          description: '本地规则 + AI 语义 + 敏感检测',
        },
      },
      empty: '当前文档没有可标注内容',
      success: '已自动添加 {count} 个标注',
      semanticOnly: '已生成 {count} 个文档语义标签',
      noCandidates: '没有发现新的可标注候选',
      failed: '自动打标失败',
    },
    semantic: {
      title: '文档语义标签',
    },
    annotation: {
      position: '位置: {start} - {end}',
    },
    empty: {
      title: '暂无标注',
      description: '选中文本后点击上方按钮添加',
    },
    a11y: {
      deleteAnnotation: '删除 {label} 标注 {start}-{end}',
    },
  },
DataClassifier: {
    header: {
      title: '分类归档',
    },
    actions: {
      autoClassify: 'AI 分类',
      analyzing: '分析中...',
    },
    auto: {
      empty: '请先选择或输入文档内容',
      success: '后端已返回 {count} 个分类标签',
      noTags: '后端未返回可用分类标签',
      failed: '后端自动分类失败',
    },
    sections: {
      category: '文档分类',
      tags: '标签',
    },
    categories: {
      technical: {
        label: '技术文档',
        keywords: ['api', 'sdk', '开发', '代码', '配置'],
      },
      product: {
        label: '产品文档',
        keywords: ['产品', '功能', '特性', '版本', '发布'],
      },
      business: {
        label: '业务文档',
        keywords: ['业务', '流程', '规范', '制度'],
      },
      legal: {
        label: '法律文档',
        keywords: ['合同', '协议', '法律', '条款', '合规'],
      },
      hr: {
        label: '人事文档',
        keywords: ['人事', '招聘', '员工', '薪酬', '培训'],
      },
      finance: {
        label: '财务文档',
        keywords: ['财务', '报表', '预算', '发票', '费用'],
      },
      other: {
        label: '其他',
        keywords: [],
      },
    },
    suggestedTags: [
      '重要',
      '公开',
      '内部',
      '机密',
      '待审核',
      '已归档',
      'v1.0',
      'v2.0',
      '最新版',
      '历史版',
      'FAQ',
      '教程',
      '指南',
      '参考',
      'API',
      '紧急',
      '长期',
      '临时',
    ],
    tags: {
      inputPlaceholder: '输入新标签...',
      aiSuggested: 'AI 推荐标签',
      showMore: '显示更多...',
    },
    summary: {
      title: '归档信息',
      category: '分类:',
      tags: '标签:',
    },
    a11y: {
      removeTagWithValue: '移除标签 {tag}',
      addTag: '添加标签',
      addTagWithValue: '添加标签 {tag}',
    },
  },
QualityChecker: {
    header: {
      title: '质量检测',
    },
    actions: {
      backendScanOn: '后端检测：开',
      backendScanOff: '后端检测：关',
      scan: '重新扫描',
      scanning: '扫描中 {progress}%',
    },
    score: {
      title: '数据质量评分',
      outOf: '/ 100',
      grades: {
        excellent: '优秀',
        good: '良好',
        pass: '及格',
        poor: '较差',
      },
    },
    checkItems: {
      chars: {
        label: '字符统计',
      },
      encoding: {
        label: '编码检测',
      },
      language: {
        label: '语言识别',
      },
      format: {
        label: '格式验证',
      },
      issues: {
        label: '问题识别',
      },
    },
    stats: {
      totalCharacters: '总字符数',
      charactersNoSpaces: '不含空格',
      wordCount: '单词数',
      lineCount: '行数',
      paragraphCount: '段落数',
      chineseCharacters: '中文字符',
      englishWords: '英文单词',
      numberCount: '数字数量',
    },
    encoding: {
      detectedEncoding: '检测编码',
      characterRange: '字符范围',
      basicMultilingualPlane: '基本多文种平面',
      hasBom: '是否含 BOM',
    },
    language: {
      simplifiedChinese: '中文 (简体)',
      english: 'English',
      mixed: '混合语言',
      primaryLanguage: '主要语言',
      chineseRatio: '中文占比',
      englishRatio: '英文占比',
    },
    format: {
      documentFormat: '文档格式',
      headingCount: '标题数量',
      listCount: '列表数量',
      hasTables: '包含表格',
      types: {
        html: 'HTML',
        markdown: 'Markdown',
        plainText: '纯文本',
      },
    },
    shared: {
      yes: '是',
      no: '否',
    },
    issues: {
      none: '未发现明显问题',
    },
    localIssues: {
      emptyParagraphs: '发现 {count} 处空段落，可能影响检索质量',
      longParagraphs: '发现 {count} 处过长段落 (>1000字符)，建议切块',
      specialChars: '发现 {count} 个控制字符，可能导致解析错误',
      duplicates: '发现 {count} 处可能的重复内容',
      urls: '发现 {count} 个 URL 链接',
    },
    backendIssues: {
      countSuffix: '（{count}）',
      detected: '后端检测：{message}',
      suggestedPatch: '后端建议：可优化治理配置（{count} 项）',
      failed: '后端检测失败（可忽略）',
    },
  },
DataCleaner: {
    header: {
      title: '智能清洗配置',
    },
    inputFormat: {
      label: '输入格式',
      options: {
        markdown: 'Markdown',
        html: 'HTML',
      },
    },
    rules: {
      title: '规则配置',
      profilesTitle: '治理预设（Profiles/脚本）',
    },
    alerts: {
      warningTitle: '清洗提示',
      infoTitle: '清洗信息',
    },
    actions: {
      reset: '重置内容',
      apply: '执行智能清洗',
      applying: '清洗中...',
    },
    llm: {
      title: 'LLM 深度清洗',
      enabled: '已启用',
      enable: '启用',
      promptTemplateLabel: '提示词',
      promptTemplatePlaceholder: '选择清洗模板',
      promptTemplateDefault: '默认清洗模板（内置）',
    },
    info: {
      cleaningStats:
        '清洗统计：行 {inputLines} -> {outputLines}（- {removed} / + {added} / ~ {changedLines}），字符 {inputChars} -> {outputChars}',
      urlsChanged: 'URL 规范化：变更 {count} 处',
      paragraphsDropped: '段落重复块去重：移除 {count} 段',
      referencesRemoved: '参考文献裁剪：移除 {count} 行',
      title: '标题：{value}',
      tags: '标签：{value}',
      language: '语言：{value}',
      languageWithConfidence: '{value}（{confidence}）',
      keywords: '关键词：{value}',
      frontmatter: 'Frontmatter：{value}',
      piiHits: '已匿名化隐私信息：{value}',
      secretsHits: '已脱敏密钥/Token：{value}',
    },
    errors: {
      filtered: '清洗后文档被过滤：{reason}',
      qualityFilterTriggered: '质量过滤触发',
      llmCleanFailedKeepPreview: 'LLM 清洗失败，已保留规则清洗结果',
      backendCleanFailed: '后端清洗失败',
    },
    diff: {
      title: '内容差异对比',
      impactTitle: 'Impact Summary',
      impact: {
        chars: 'chars',
        lines: 'lines',
        diff: 'diff',
        piiSecrets: 'PII / Secrets',
        urlsChanged: 'urls_changed',
        paragraphsDropped: 'paragraphs_dropped',
        referencesRemovedLines: 'references_removed_lines',
      },
      issuesTitle: '检测到的问题（Best-effort）',
      applySuggestionHint: '已生成治理建议，可一键应用到当前配置（会覆盖对应字段）。',
      applySuggestion: '应用建议',
      noIssueHint: '暂无明显问题提示。',
      unifiedDiff: 'Unified Diff',
      truncated: '已截断',
      noDiffHint: '暂无差异可显示（或尚未执行清洗）。',
    },
    severity: {
      error: 'ERROR',
      warning: 'WARNING',
      info: 'INFO',
    },
  },
DataGovernancePanel: {
    header: {
      title: '数据治理',
      subtitle: '清洗、标注与结构修复',
      workspaceSubtitle: '文档清洗、标注与结构修复',
      emptyBadge: '治理',
      mainBadge: '工作台',
    },
    inbound: {
      title: 'Inbound',
      fromLabel: 'from',
      datasetLabel: 'dataset_id',
      profileLabel: 'governance_profile_ref',
      description:
        '提示：该页当前仅做引导展示；如需精确复现治理效果，请在入库配置或规则中启用对应的 pipeline/governance 配置。',
      close: '关闭提示',
    },
    tabs: {
      quality: {
        label: '质量检测',
        description: '检测文档质量与格式问题',
      },
      clean: {
        label: '智能清洗',
        description: '修复格式错误与乱码',
      },
      annotate: {
        label: '数据标注',
        description: '标记关键实体与敏感信息',
      },
      classify: {
        label: '分类归档',
        description: '设置文档分类与标签',
      },
    },
    actions: {
      reset: '重置',
      save: '保存',
      pushToChunkPreview: '推送到切块预览',
    },
    scope: {
      title: 'Dataset Scope',
      allDatasets: '全部数据集与解析工作台',
      placeholder: '选择数据集',
      datasetAll: '全部来源',
      datasetScoped: '数据集绑定',
      datasetOptionWithCount: '{name}（{count}）',
      datasetScopeHint: '默认显示解析工作台文档；选择数据集后显示已入库文档。',
      datasetScopeSelectedHint: '当前只显示该数据集下的入库文档，点击文件可预览解析内容。',
      allDescription: '显示解析工作区与全部知识库文档，共 {count} 个可治理文件。',
      selectedDescription: '当前只显示该数据集下的知识库文档，共 {count} 个可治理文件。',
      syncing: '同步知识库文档中',
      synced: '已同步 {count} 个文件',
      sourceKnowledge: '知识库',
      sourceParsing: '解析工作区',
    },
    toasts: {
      uploadCancelled: '已取消解析',
      fileDeleted: '已删除文件',
      zipExtractFailed: 'ZIP 解压失败：{filename}',
      zipNoFilesFound: 'ZIP 中未找到文件：{filename}',
      zipNoSupportedFiles: 'ZIP 中没有可解析文件：{filename}',
      zipAdded: '已从 ZIP 添加 {added} 个文件',
      zipAddedWithSkipped: '已从 ZIP 添加 {added} 个文件（跳过 {skipped} 个）',
      parsedAndAdded: '已解析并加入：{count} 个文件',
      skippedUnsupported: '已跳过 {count} 个不支持的文件',
      parseFailed: '解析失败，请稍后重试',
      resultsSaved: '已保存治理结果',
      filenameCopied: '文件名已复制',
      fileRemoved: '文件已移除',
    },
    emptyUpload: {
      openUploadDialog: '打开文件上传对话框',
      uploadingTitle: '正在解析文档...',
      idleTitle: '拖拽文档至全息工作台',
      uploadingDescription: 'AI 正在分析文档结构并提取内容，请稍候...',
      idleDescription: '支持 PDF, Word, Excel, TXT, MD, ZIP 等格式。即刻开启智能治理流程。',
      structureTitle: '文档结构',
      selectLocalFiles: '选择本地文件',
      cancelParsing: '取消解析',
      stages: {
        parse: '智能解析',
        quality: '质量检测',
        clean: '自动清洗',
      },
    },
    libraryFile: {
      notice: '该条目来自文档库（未保留本地 PDF 原文件）',
      description: '{notice}。可查看解析后的 Markdown；如需 PDF 预览请重新上传该文件。',
      unknownFile: '未知文件',
      badge: '文档库',
      pending: '待补原件',
      copyName: '复制名称',
      removeButton: '移除文件',
      removeDialog: {
        title: '移除该文件？',
        description: '将从文档库中移除该文件记录。此操作不可恢复。',
        confirm: '移除',
        cancel: '返回',
      },
    },
    sidebar: {
      allFolders: '全部目录',
      expand: '展开侧边栏',
      collapse: '收起侧边栏',
      adjustWidth: '调整侧边栏宽度',
      rootFolder: '根目录',
      folderPlaceholder: '切换目录',
      searchPlaceholder: '搜索当前目录文件...',
      filesTitle: '文件 ({count})',
      emptyDirectory: '该目录暂无文件',
      scoreLabel: '{score} 分',
      notScanned: '未检测',
      cleaned: '已清洗',
      needsAttention: '需关注',
      foldersHeader: '目录树',
    },
    stats: {
      storage: '存储进度',
      avgScore: '平均分',
      processedRatio: '已处理 {done}/{total}',
      avgScoreInline: '平均 {score} 分',
    },
    canvas: {
      livePreview: '实时预览',
      sourceEditor: '源码编辑',
      viewModes: {
        preview: '预览',
        edit: '编辑',
        original: '对比',
      },
      viewSource: '查看源码',
      viewRendered: '查看渲染',
      modified: '已修改',
    },
    panel: {
      title: '治理工具箱',
      expand: '展开右侧面板',
      collapse: '收起右侧面板',
      adjustWidth: '调整右侧面板宽度',
    },
    emptySelection: {
      title: '选择文件开始治理',
      description: '从左侧列表选择一个文件，使用右侧工具箱进行质量检测、清洗与标注。',
    },
    dialogs: {
      deleteFile: {
        title: '删除文件？',
        description: '你将删除文件 {filename}。此操作不可撤销。',
        cancel: '取消',
        confirm: '删除',
      },
    },
    a11y: {
      openFile: '打开文件：{filename}',
      deleteFile: '删除文件：{filename}',
    },
  }
} as const

export default governanceMessages
