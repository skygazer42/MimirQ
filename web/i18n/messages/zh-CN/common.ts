const commonMessages = {
Layout: {
    skipToMainContent: '跳到主要内容',
  },
Common: {
    loading: '加载中...',
    error: '发生错误',
    retry: '重试',
    cancel: '取消',
    save: '保存',
    close: '关闭',
  },
CommonUi: {
    modeToggle: {
      ariaLabel: '切换主题',
      light: '浅色',
      dark: '深色',
      system: '跟随系统',
    },
    breadcrumb: {
      navLabel: 'Breadcrumb',
      routes: {
        datasets: '数据集',
        knowledge: '知识库',
        settings: '设置',
        graph: '知识图谱',
        evaluations: '评测',
        history: '历史记录',
        prompts: '提示词',
        profile: '概览',
        ingestion: '数据导入',
        precheck: '预检查',
        workflow: '工作流',
        kg: '知识图谱',
        tables: '数据表',
        health: '健康检查',
        evidence: '溯源',
        dbCatalog: '数据目录',
      },
    },
    searchInput: {
      placeholder: '搜索…',
      clearLabel: '清除搜索',
    },
    tagInput: {
      placeholder: '添加标签（回车 / 逗号分隔）',
      removeLabel: '移除标签 {tag}',
      add: '添加',
    },
    confirmDialog: {
      confirm: '确认',
      cancel: '返回',
    },
    statusBadge: {
      pending: '等待',
      processing: '处理中',
      completed: '已完成',
      failed: '失败',
      quarantined: '已隔离',
      cancelled: '已取消',
    },
    pageLoading: {
      message: '正在加载...',
      srMessage: 'Loading',
    },
    command: {
      title: '命令中心',
      description: '输入命令或搜索应用内页面、数据和对话结果。',
    },
    pipelineVisualizer: {
      upload: '上传',
      parse: '解析',
      chunk: '切片',
      index: '索引',
    },
    themeCustomizer: {
      openLabel: '打开主题定制',
      title: '主题定制',
      description: '选择界面风格与强调主色',
      resetAppearance: '重置外观',
      surfaceLabel: '界面风格',
      surfacePresetLabel: '选择界面风格：{name}',
      surfaceSwatch: '底色',
      primarySwatch: '主色',
      surfacePresets: {
        ocean: {
          title: '默认海洋',
          description: '清透冰蓝表面与深海军蓝主色，保持 MimirQ 默认层级。',
        },
        deepsea: {
          title: '深海留白',
          description: '雾白蓝灰表面与克制的深海蓝焦点，留白充足、层级清晰。',
        },
        neutral: {
          title: '中性白',
          description: '纯白表面、石墨文字与浅灰层级，仅保留必要的业务状态色。',
        },
        classic: {
          title: '经典白灰',
          description: '浅灰白背景、深灰正文与经典蓝主色，清爽且阅读友好。',
        },
        earth: {
          title: '米白大地',
          description: '暖米白背景与柔和灰褐层次，长时间阅读更温和。',
        },
      },
      colorLabel: '主色调',
      useSurfaceColor: '使用当前界面风格的自动主色',
      autoColor: '自动',
      surfaceColorActive: '当前：{style} · 自动主色 {color}',
      customColorActive: '当前：{style} · 自定义主色 {color}',
      modeLabel: '模式',
      presetLabel: '选择主色调：{name}',
      selected: '已选中',
    },
    fileQueueItem: {
      pending: '等待解析',
      parsing: '解析中',
      parsed: '已完成',
      error: '解析失败',
      folderLabel: '目录：',
      sourcePathLabel: 'ZIP：',
      pages: '{count} 页',
      retry: '重试',
      removeLabel: '移除文件',
      removeTitle: '移除',
    },
  },
RouteBoundaries: {
    notFound: {
      title: '页面不存在',
      description: '你访问的地址可能已被移除或暂时不可用。',
      goHome: '返回首页',
      goKnowledge: '前往知识库',
    },
    loading: {
      pageSr: '页面加载中…',
    },
    error: {
      title: '页面加载失败',
      message: '发生了一个临时错误，请重试或返回首页继续操作。',
      retry: '重试',
      home: '返回首页',
      requestId: '请求 ID：request_id={requestId}',
      errorId: '错误 ID：{errorId}',
    },
  }
} as const

export default commonMessages
