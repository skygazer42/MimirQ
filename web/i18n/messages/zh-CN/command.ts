const commandMessages = {
CommandMenu: {
    header: {
      title: 'Command Center',
      hint: '输入 / 查看快捷动作 · 试试 ? / g d / g c / g g / g o / f s / g v',
    },
    search: {
      placeholder: '输入命令或搜索...',
      empty: '未找到相关结果',
    },
    groups: {
      slash: '快捷指令',
      keyboardWorkflow: '键盘工作流',
      viewerShortcuts: '文档查看器快捷键',
      shortcutMap: '工作流快捷键地图',
      navigation: '导航',
      aiActions: 'AI 快捷动作',
      modules: '模块与工作台',
      documents: '文档',
      datasets: '数据集',
      conversations: '对话',
      actions: '操作',
      theme: '主题',
    },
    currentView: {
      graph: {
        prompt: '请基于当前图谱视图，总结关键实体、关系模式、异常断点，并给出最值得继续下钻的节点。',
        description: '把当前图谱视图送入对话区，自动生成下钻建议。',
      },
      knowledge: {
        prompt: '请基于当前知识库工作台，总结文档状态、导入风险和最值得优先处理的事项。',
        description: '把当前知识库上下文转成一条可直接发起的分析问题。',
      },
      datasets: {
        prompt: '请基于当前数据集页面，总结关键质量信号、风险项，以及建议的下一步治理动作。',
        description: '针对当前数据集页面生成一条诊断型提问。',
      },
      settings: {
        prompt: '请基于当前系统设置页面，指出高风险配置、建议保守值和需要复核的项。',
        description: '针对当前设置视图生成一条配置审查提问。',
      },
      observability: {
        prompt: '请基于当前可观测/报表页面，总结异常指标、可能根因和建议的排查顺序。',
        description: '把当前监控视图转成可直接追问的调查提示。',
      },
      default: {
        prompt: '请分析我当前所在页面的重点信息、潜在风险，以及建议的下一步操作。',
        description: '将当前视图整理成一条可直接发送的分析问题。',
      },
    },
    keyChords: {
      documents: {
        label: 'Go to Documents',
        description: '跳到知识库文档工作台。',
      },
      chat: {
        label: 'Go to Chat',
        description: '返回主对话视图。',
      },
      graph: {
        label: 'Go to Graph',
        description: '打开图谱工作台。',
      },
      observability: {
        label: 'Go to Observability',
        description: '打开可观测中心，继续排查指标、日志和链路异常。',
      },
      slice: {
        label: 'Find Slice',
        description: '进入切片工作台，继续检索与诊断。',
      },
      resume: {
        label: 'Resume Viewer Context',
        description: '恢复最近一次文档/引用定位。',
        emptyDescription: '最近没有可恢复的文档定位。',
      },
    },
    shortcutGuide: {
      open: {
        label: '打开 Command Center',
        description: '全局呼出命令中心，并继续搜索页面、数据集、对话与快捷动作。',
      },
      help: {
        label: '查看快捷键地图',
        description: '当光标不在输入框时，直接打开当前这份快捷键说明。',
      },
      chordPrefix: '导航 Chord ·',
      stagePrevNext: {
        label: '切换 Trace Stage',
        description: 'RAG Trace 时间线聚焦后，在 pipeline stages 之间左右切换。',
      },
      stageArrows: {
        label: '切换 Trace Stage',
        description: '和 h/l 等价，用方向键快速浏览 pipeline inspector。',
      },
      sliceFocus: {
        label: '切片焦点跳转',
        description: 'Document Viewer 内在检索命中或已加载切片之间循环切换。',
      },
    },
    slash: {
      commands: {
        resume: {
          label: '恢复最近文档上下文',
          description: '重新打开最近一次查看的文档、切片与高亮位置。',
          emptyDescription: '最近没有可恢复的文档定位。',
          keywords: ['resume', 'viewer', 'document', 'citation', '恢复', '文档', '引用', '继续查看'],
        },
        upload: {
          label: '上传文档',
          description: '直达知识库工作台，继续上传、整理和查看导入状态。',
          keywords: ['upload', '文档', '知识库', '导入'],
        },
        analyze: {
          label: '分析当前视图',
          description: '将当前视图整理成一条可直接发送的分析问题。',
          keywords: ['analyze', '分析', '当前视图', '总结', '诊断'],
        },
        report: {
          label: '下载审计报告',
          description: '在入库盘点页中快速打开当前审计报告的 PDF 打印视图。',
          keywords: ['report', 'pdf report', 'audit report', '下载报告', '审计报告', 'PDF', '盘点报告'],
        },
        stats: {
          label: '查看统计与诊断',
          description: '打开用量/配额视图，快速查看 tokens、成本和系统诊断入口。',
          keywords: ['stats', 'usage', 'diagnostics', 'quota', 'token', 'cost', '统计', '诊断', '用量'],
        },
        retryFailed: {
          label: '重试失败任务',
          description: '在入库监控页中批量重试当前失败/取消任务。',
          keywords: ['retry failed', 'retry', 'ingestion', 'failed', '重试', '失败任务', '入库监控'],
        },
        pauseActive: {
          label: '暂停活动任务',
          description: '在入库监控页中批量取消当前运行中的任务。',
          keywords: ['pause active', 'cancel active', 'ingestion', '暂停', '取消运行任务', '活动任务'],
        },
        demo: {
          label: '切换虚拟数据',
          description: '在入库监控页里切换控制室 demo 数据，用于演示交互与可视化。',
          keywords: ['demo', 'mock data', 'virtual data', 'ingestion', '虚拟数据', '演示', '模拟数据'],
        },
        precheck: {
          label: '打开入库预检',
          description: '进入数据集预检扫描，先做入库前摸底再决定是否真正导入。',
          keywords: ['precheck', 'ingestion precheck', 'dataset precheck', '预检', '入库预检', '预检扫描'],
        },
        datasets: {
          label: '打开数据集',
          description: '跳到数据集列表，查看质量信号与治理入口。',
          keywords: ['datasets', '数据集', '质量', '治理'],
        },
        history: {
          label: '打开问答历史',
          description: '查看最近问答记录，便于复盘与复用。',
          keywords: ['history', 'qa', '对话历史', '复盘'],
        },
        graph: {
          label: '打开图谱工作台',
          description: '跳到图谱视图，查看实体关系和路径分析。',
          keywords: ['graph', '图谱', '关系', '实体'],
        },
        diagnostics: {
          label: '打开运行诊断',
          description: '进入系统诊断页，查看健康状态、依赖和前端运行信息。',
          keywords: ['diagnostics', 'health', 'observability', '诊断', '健康检查'],
        },
        settings: {
          label: '打开系统设置',
          description: '快速进入模型、RAG 和治理配置。',
          keywords: ['settings', '设置', 'rag', '配置'],
        },
        parsing: {
          label: '打开解析工作台',
          description: '进入文档解析工作台，检查切分策略、解析质量与提取结果。',
          keywords: ['parsing', 'parser', 'chunking', 'extract', '解析', '文档解析', '切分', '抽取', '解析工作台'],
        },
        reports: {
          label: '打开数据报告导出',
          description: '按数据集生成质量、治理和 RAG 审计报告，支持导出分享。',
          keywords: ['reports', 'report', 'analytics', 'dashboard', '报表', '报告', '数据集报告', '数据报告导出', '质量报告', '审计'],
        },
        observability: {
          label: '打开可观测中心',
          description: '直达可观测页面，追踪指标、日志和诊断线索。',
          keywords: ['observability', 'monitoring', 'metrics', 'logs', 'trace', '可观测', '监控', '指标', '日志', '链路'],
        },
        governance: {
          label: '打开数据治理',
          description: '进入数据治理工作台，处理画像、规则与质量治理任务。',
          keywords: ['governance', 'data governance', 'policy', 'compliance', '数据治理', '治理', '规则', '合规', '画像'],
        },
        accessReview: {
          label: '打开访问审查',
          description: '进入访问审查工作台，快速检查权限分配和高风险访问。',
          keywords: ['access review', 'rbac', 'permission', 'admin', 'access', '访问审查', '权限', '角色', '管理员'],
        },
      },
    },
    viewerShortcuts: {
      resume: {
        label: '恢复最近文档上下文',
        description: '重新打开最近一次文档/引用定位，减少误关后的重找成本。',
      },
      focusSearch: {
        label: '聚焦切片搜索',
        description: '在文档查看器切片页中直接把焦点拉到搜索框。',
      },
      cycleHits: {
        label: '切换命中切片',
        description: '在当前命中列表里快速前后切换。',
      },
      find: {
        label: '打开切片查找',
        description: '在切片页里快速开始关键字定位。',
      },
      dismiss: {
        label: '清空搜索或关闭查看器',
        description: '优先清空切片搜索；没有搜索词时直接关闭查看器。',
      },
    },
    modules: {
      knowledge: {
        label: '知识库工作台',
        description: '管理文档导入、索引状态与知识库检索质量。',
        keywords: ['workbench modules', 'knowledge', 'document', 'kb', '上传', '知识库', '文档', '导入', '索引'],
      },
      graph: {
        label: '图谱工作台',
        description: '查看实体关系、路径洞察和图谱诊断。',
        keywords: ['graph', 'entity', 'relationship', '图谱', '实体', '关系', '路径'],
      },
      slices: {
        label: '切片工作台',
        description: '定位切片召回结果，检查检索命中与上下文。',
        keywords: ['slice', 'chunk', 'retrieval', 'find', '切片', '召回', '检索', 'chunk-preview'],
      },
      parsing: {
        label: '解析工作台',
        description: '检查文档解析策略、切分结果和提取质量。',
        keywords: ['parsing', 'parser', 'extract', '文档解析', '解析', '切分', '抽取'],
      },
      reports: {
        label: '数据报告导出',
        description: '生成数据集质量、治理和 RAG 审计交付物。',
        keywords: ['reports', 'report', 'analytics', 'dashboard', '报表', '报告', '数据集报告', '数据报告导出', '质量报告', '审计'],
      },
      observability: {
        label: '可观测中心',
        description: '查看监控指标、日志与链路诊断线索。',
        keywords: ['observability', 'monitoring', 'metrics', 'logs', 'trace', '可观测', '监控', '日志'],
      },
      governance: {
        label: '数据治理',
        description: '处理治理规则、画像与合规策略。',
        keywords: ['governance', 'policy', 'compliance', '数据治理', '治理', '规则', '合规', '画像'],
      },
      accessReview: {
        label: '访问审查',
        description: '复核权限分配与高风险访问行为。',
        keywords: ['access review', 'rbac', 'permission', 'admin', '访问审查', '权限', '角色'],
      },
    },
    navigation: {
      home: '对话',
      newConversation: '新对话',
      knowledge: '知识库',
      parsing: '文档解析',
      history: '问答历史',
      settings: '设置',
    },
    aiAction: {
      label: '执行自然语言指令',
      description: '直接把当前输入发送给 AI，并立即开始执行。',
    },
    results: {
      modulesEmpty: '未找到匹配的模块',
      documentsLoading: '搜索中…',
      documentsEmpty: '未找到文档',
      datasetsLoading: '搜索中…',
      datasetsEmpty: '未找到数据集',
      conversationsLoading: '搜索中…',
      conversationsEmpty: '未找到对话',
      untitledConversation: '未命名对话',
    },
    actions: {
      uploadDocument: '上传文档',
      ragSettings: 'RAG 设置',
    },
    theme: {
      light: '浅色模式',
      dark: '深色模式',
      system: '跟随系统',
    },
  }
} as const

export default commandMessages
