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
    ingestionWorkflow: {
      navLabel: '入库流程',
      parsing: '解析',
      governance: '治理',
      chunk: '切块',
      chat: '对话',
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
      description: '自定义界面颜色与风格',
      resetAppearance: '重置外观',
      surfaceLabel: '背景风格',
      surfacePresetLabel: '选择背景风格：{name}',
      surfacePresets: {
        ocean: {
          title: '默认海洋',
          description: '冷静蓝绿，保持当前默认观感。',
        },
        classic: {
          title: '经典白灰',
          description: '背景 #F8F9FA，正文深灰，强调蓝色，干净现代且阅读友好。',
        },
        earth: {
          title: '米白大地',
          description: '暖米白背景与柔和灰褐层次，长时间阅读更温和。',
        },
      },
      colorLabel: '主色调',
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
