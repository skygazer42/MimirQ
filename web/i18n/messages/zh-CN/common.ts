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
      unlimited: '不限数量',
      limitError: '最多添加 {maxTags} 个标签，未添加的内容已保留。',
      lengthError: '每个标签最多 {maxLen} 个字符，请修改保留的内容。',
      pendingError: '请先添加输入中的标签，或清空后保存。',
    },
    confirmDialog: {
      confirm: '确认',
      cancel: '返回',
      failed: '操作失败，请重试。',
    },
    statusBadge: {
      pending: '等待',
      processing: '处理中',
      completed: '已完成',
      failed: '失败',
      quarantined: '已隔离',
      cancelled: '已取消',
      deleting: '删除中',
    },
    pageLoading: {
      message: '正在加载...',
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
      title: '外观',
      resetAppearance: '恢复默认外观',
      resetLabel: '重置',
      backToAccount: '返回账户菜单',
      surfaceLabel: '界面底色',
      surfacePresetLabel: '{name}底色',
      surfacePresets: {
        ocean: {
          title: '暖石默认',
          description: '暖石阅读表面，品牌与状态色独立。',
        },
        neutral: {
          title: '纯白',
          description: '纯白阅读表面。',
        },
        classic: {
          title: '浅灰',
          description: '浅灰中性阅读表面。',
        },
        earth: {
          title: '米白',
          description: '米白阅读表面。',
        },
      },
      colorLabel: '界面强调色',
      useSurfaceColor: '使用默认品牌配色',
      autoColor: '默认',
      modeLabel: '显示模式',
      presetLabel: '{name}强调色',
      colors: {
        terracotta: '陶土',
        sky: '晴空蓝',
        graphite: '石墨',
        indigo: '靛蓝',
        violet: '紫色',
      },
    },
  },
  RouteBoundaries: {
    notFound: {
      title: '页面不存在',
      description: '请检查网址是否正确。',
      goHome: '返回首页',
      goKnowledge: '前往知识库',
    },
    loading: {
      pageSr: '页面加载中…',
    },
    error: {
      title: '页面加载失败',
      retry: '重试',
      home: '返回首页',
      requestId: '请求 ID：request_id={requestId}',
      errorId: '错误 ID：{errorId}',
    },
  },
} as const

export default commonMessages
