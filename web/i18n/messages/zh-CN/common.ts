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
      openLabel: '打开外观设置',
      title: '外观',
      resetAppearance: '恢复默认配色',
      resetLabel: '重置',
      surfaceLabel: '配色',
      surfacePresetLabel: '{name}配色',
      surfacePresets: {
        ocean: {
          title: '默认',
          description: '雾灰底色，墨色主色。',
        },
        deepsea: {
          title: '靛蓝',
          description: '蓝灰底色，靛蓝主色。',
        },
        neutral: {
          title: '纯白',
          description: '纯白底色，黑色主色。',
        },
        classic: {
          title: '浅灰',
          description: '浅灰底色，蓝色主色。',
        },
        earth: {
          title: '米白',
          description: '米白底色，棕色主色。',
        },
      },
      colorLabel: '主色',
      useSurfaceColor: '使用配色默认主色',
      autoColor: '自动',
      modeLabel: '显示模式',
      presetLabel: '{name}主色',
      colors: {
        sky: '天蓝',
        graphite: '黑色',
        rose: '玫红',
        orange: '橙色',
        green: '绿色',
        violet: '紫色',
        yellow: '金黄',
      },
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
