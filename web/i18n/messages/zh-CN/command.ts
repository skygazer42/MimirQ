const commandMessages = {
  CommandMenu: {
    header: {
      title: '命令中心',
      description: '查找内容，或向知识库提问',
      hint: '快捷键',
    },
    search: {
      label: '搜索内容或输入问题',
      placeholder: '搜索、提问，或输入 / 查看指令',
      empty: '未找到相关结果',
    },
    keyboard: {
      close: '关闭命令中心',
      navigate: '选择',
      execute: 'Enter 执行',
      help: '快捷键',
      helpHint: '输入 ? 查看快捷键',
    },
    groups: {
      slash: '快捷指令',
      keyboardWorkflow: '快捷工作流',
      viewerShortcuts: '文档查看器快捷键',
      shortcutMap: '快捷键一览',
      navigation: '导航',
      aiActions: '提问',
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
        description: '在对话中分析当前图谱',
      },
      knowledge: {
        prompt: '请基于当前知识库工作台，总结文档状态、导入风险和最值得优先处理的事项。',
        description: '在对话中分析文档与导入状态',
      },
      datasets: {
        prompt: '请基于当前数据集页面，总结关键质量信号、风险项，以及建议的下一步治理动作。',
        description: '在对话中分析数据集质量',
      },
      settings: {
        prompt: '请基于当前系统设置页面，指出高风险配置、建议保守值和需要复核的项。',
        description: '在对话中检查当前配置',
      },
      observability: {
        prompt: '请基于当前可观测/报表页面，总结异常指标、可能根因和建议的排查顺序。',
        description: '在对话中分析监控指标',
      },
      default: {
        prompt: '请分析我当前所在页面的重点信息、潜在风险，以及建议的下一步操作。',
        description: '在对话中分析当前页面',
      },
    },
    keyChords: {
      documents: {
        label: '打开知识库',
        description: '查看文档与索引状态',
      },
      chat: {
        label: '打开对话',
        description: '回到知识问答工作台',
      },
      graph: {
        label: '打开知识图谱',
        description: '查看实体、关系与路径分析',
      },
      observability: {
        label: '打开可观测性',
        description: '排查指标、日志与链路异常',
      },
      slice: {
        label: '打开切块预览',
        description: '检索切块与诊断召回结果',
      },
      resume: {
        label: '恢复文档位置',
        description: '回到最近查看的文档与引用位置',
        emptyDescription: '最近没有可恢复的文档定位',
      },
    },
    shortcutGuide: {
      open: {
        label: '打开命令中心',
        description: '搜索页面、数据集、对话与快捷动作。',
      },
      help: {
        label: '查看快捷键',
        description: '光标在输入框外时可打开说明。',
      },
      chordPrefix: '连续按键 ·',
      stagePrevNext: {
        label: '切换追踪阶段',
        description: '聚焦 RAG 追踪时间线后，在前后阶段间切换。',
      },
      stageArrows: {
        label: '切换追踪阶段',
        description: '使用方向键切换前后处理阶段。',
      },
      sliceFocus: {
        label: '切片焦点跳转',
        description: '在文档查看器中循环切换检索命中或已加载切片。',
      },
    },
    slash: {
      commands: {
        resume: {
          label: '继续查看文档',
          description: '回到上次查看的位置',
          emptyDescription: '暂无最近打开的文档',
          keywords: ['resume', 'viewer', 'document', 'citation', '恢复', '文档', '引用', '继续查看'],
        },
        upload: {
          label: '上传文档',
          description: '导入文档到知识库',
          keywords: ['upload', '文档', '知识库', '导入'],
        },
        analyze: {
          label: '分析当前视图',
          description: '在对话中分析当前页面',
          keywords: ['analyze', '分析', '当前视图', '总结', '诊断'],
        },
        report: {
          label: '查看数据集预检报告',
          description: '选择数据集，进入文档预检查看和导出报告',
          keywords: ['report', 'ingestion report', '下载报告', '入库报告', '预检报告'],
        },
        stats: {
          label: '查看统计与诊断',
          description: '查看用量、配额和诊断',
          keywords: ['stats', 'usage', 'diagnostics', 'quota', 'token', 'cost', '统计', '诊断', '用量'],
        },
        precheck: {
          label: '预检数据集',
          description: '选择数据集，进入文档预检启动扫描',
          keywords: ['precheck', 'ingestion precheck', 'dataset precheck', '预检', '入库预检', '预检扫描'],
        },
        datasets: {
          label: '打开数据集',
          description: '查看数据集与质量检查',
          keywords: ['datasets', '数据集', '质量', '治理'],
        },
        history: {
          label: '打开问答历史',
          description: '查看之前的问答记录',
          keywords: ['history', 'qa', '对话历史', '复盘'],
        },
        graph: {
          label: '打开知识图谱',
          description: '查看实体、关系和路径',
          keywords: ['graph', '图谱', '关系', '实体'],
        },
        diagnostics: {
          label: '打开诊断',
          description: '检查服务状态和运行环境',
          keywords: ['diagnostics', 'health', 'observability', '诊断', '健康检查'],
        },
        settings: {
          label: '打开设置',
          description: '配置模型、检索与数据治理',
          keywords: ['settings', '设置', 'rag', '配置'],
        },
        parsing: {
          label: '打开文档解析',
          description: '检查文档解析与切分结果',
          keywords: ['parsing', 'parser', 'chunking', 'extract', '解析', '文档解析', '切分', '抽取', '解析工作台'],
        },
        reports: {
          label: '打开数据报告',
          description: '查看质量、治理和检索报告',
          keywords: [
            'reports',
            'report',
            'analytics',
            'dashboard',
            '报表',
            '报告',
            '数据报告',
            '数据集报告',
            '质量报告',
            '审计',
          ],
        },
        observability: {
          label: '打开可观测中心',
          description: '查看指标、日志与链路',
          keywords: [
            'observability',
            'monitoring',
            'metrics',
            'logs',
            'trace',
            '可观测',
            '监控',
            '指标',
            '日志',
            '链路',
          ],
        },
        governance: {
          label: '打开数据治理',
          description: '管理质量规则与治理任务',
          keywords: [
            'governance',
            'data governance',
            'policy',
            'compliance',
            '数据治理',
            '治理',
            '规则',
            '合规',
            '画像',
          ],
        },
      },
    },
    viewerShortcuts: {
      resume: {
        label: '继续查看最近的文档',
        description: '回到上次查看的文档或引用位置。',
      },
      focusSearch: {
        label: '跳到切片搜索框',
        description: '在文档查看器的「切片」页可用。',
      },
      cycleHits: {
        label: '切换命中切片',
        description: '查看上一条或下一条命中。',
      },
      find: {
        label: '打开切片查找',
        description: '在切片页搜索关键词。',
      },
      dismiss: {
        label: '清空搜索或关闭查看器',
        description: '有搜索词时先清空。搜索框为空时关闭查看器。',
      },
    },
    modules: {
      ontology: {
        label: '企业本体',
        description: '建模、校验并运行企业业务定义',
        keywords: ['ontology', 'enterprise ontology', '企业本体', '本体', '建模', '规则', '动作'],
      },
      knowledge: {
        label: '知识库',
        description: '管理文档导入、索引状态与检索质量',
        keywords: ['workbench modules', 'knowledge', 'document', 'kb', '上传', '知识库', '文档', '导入', '索引'],
      },
      graph: {
        label: '知识图谱',
        description: '查看实体关系、路径和图谱诊断',
        keywords: ['graph', 'entity', 'relationship', '图谱', '实体', '关系', '路径'],
      },
      slices: {
        label: '切块预览',
        description: '定位召回结果，检查检索命中与上下文',
        keywords: ['slice', 'chunk', 'retrieval', 'find', '切片', '召回', '检索', 'chunk-preview'],
      },
      parsing: {
        label: '文档解析',
        description: '检查解析策略、切分结果和提取质量',
        keywords: ['parsing', 'parser', 'extract', '文档解析', '解析', '切分', '抽取'],
      },
      reports: {
        label: '数据报告',
        description: '查看数据集质量、治理和 RAG 报告',
        keywords: [
          'reports',
          'report',
          'analytics',
          'dashboard',
          '报表',
          '报告',
          '数据报告',
          '数据集报告',
          '质量报告',
          '审计',
        ],
      },
      observability: {
        label: '可观测性',
        description: '查看指标、日志和链路',
        keywords: ['observability', 'monitoring', 'metrics', 'logs', 'trace', '可观测', '监控', '日志'],
      },
      governance: {
        label: '数据治理',
        description: '处理治理规则、画像与合规策略',
        keywords: ['governance', 'policy', 'compliance', '数据治理', '治理', '规则', '合规', '画像'],
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
      label: '向知识库提问',
    },
    results: {
      modulesEmpty: '未找到匹配的模块',
      documentsLoading: '搜索中…',
      documentsEmpty: '未找到文档',
      documentsError: '文档搜索失败',
      datasetsLoading: '搜索中…',
      datasetsEmpty: '未找到数据集',
      datasetsError: '数据集搜索失败',
      conversationsLoading: '搜索中…',
      conversationsEmpty: '未找到对话',
      conversationsError: '对话搜索失败',
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
  },
} as const

export default commandMessages
