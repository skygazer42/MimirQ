const auditMessages = {
AuditPage: {
    title: '审计日志',
    description: '关键操作留痕',
    strip: {
      total: '总事件',
      currentPage: '当前页',
      filters: '筛选条件',
      status: '列表状态',
      loading: '加载中',
      ready: '已就绪',
      empty: '空结果',
    },
    presets: {
      quick: '快速筛选',
      accessReviewDaily: '访问审查',
      indexAuditDaily: '索引审计',
      evidenceDriftDaily: '证据策略',
      accessGraphExport: '访问回溯',
    },
    filters: {
      action: '动作',
      actionPlaceholder: '选择后端审计日志中的动作',
      actorId: '操作者',
      actorIdPlaceholder: '选择操作者',
      requestId: '请求 ID',
      requestIdPlaceholder: '选择请求',
      resourceType: '资源类型',
      resourceTypePlaceholder: '选择资源类型',
      resourceId: '资源 ID',
      resourceIdPlaceholder: '选择资源',
      since: '开始时间',
      until: '结束时间',
      more: '收起',
    },
    retention: {
      title: '导出与清理',
      description: '导出复用当前筛选；清理支持保留策略或当前筛选范围，默认预演。',
      export: '导出审计日志',
      purge: '清理审计日志',
      actionType: '操作类型',
      days: '保留天数',
      maxDelete: '最多清理',
      dryRun: '仅预演',
      gzip: 'gzip',
      includeSensitive: '包含敏感字段',
      advanced: '高级筛选',
      operationResult: '审计操作结果',
      resultEmpty: '导出或清理后，这里展示执行摘要；原始响应默认收起。',
    },
    table: {
      time: '时间',
      actor: '操作者',
      event: '事件名称',
      resource: '资源',
      action: '操作',
    },
    actions: {
      refresh: '刷新',
      reset: '重置',
      requestFilterTitle: '按请求 ID 过滤',
    },
    labels: {
      quickPresets: '快速预设：',
    },
    pagination: {
      status: '总计：{total} · 页码：{page}/{totalPages}',
      previous: '上一页',
      next: '下一页',
    },
    emptyState: {
      title: '暂无审计记录',
      description: '当前筛选条件下没有找到任何审计日志。',
    },
    alerts: {
      unableToLoad: '无法加载审计日志。请确认你是管理员，并且后端已更新到包含 /api/v1/audit 的版本。',
    },
    toasts: {
      copySuccess: '已复制详情 JSON',
      copyFailure: '复制失败',
    },
    errors: {
      loadLogs: '加载审计日志失败',
    },
  },
} as const

export default auditMessages
