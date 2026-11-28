'use client'

import { BarChart3, Search, ShieldCheck } from '@/components/icons'
import { SplitEmptyStudio } from '@/components/ui/split-empty-studio'
import type { DiagnosticsController } from './use-diagnostics'
import styles from './diagnostics.module.css'

const guides = {
  retrieval: {
    title: '尚未运行检索预览',
    description: '运行检索预览，核对引用、链路与评分。',
    stepsHeading: '检索诊断维度',
    steps: [
      { index: '01', title: '召回与引用核对', description: '对照各通道候选与最终引用，查看返回的来源片段。' },
      { index: '02', title: '检索链路与耗时', description: '沿过滤、融合与重排过程，核对配置和执行耗时。' },
      { index: '03', title: '相关性与安全评分', description: '查看实际返回的质量读数，未返回的评分保持未知。' },
    ],
  },
  drift: {
    title: '尚未运行漂移检查',
    description: '比较活动分块的向量，检查距离与偏移。',
    stepsHeading: '向量检查维度',
    steps: [
      { index: '01', title: '可比样本范围', description: '按采样上限读取活动分块，无可比样本时保留未评估。' },
      { index: '02', title: '距离与超阈值比例', description: '查看平均距离与达到阈值的样本数量。' },
      { index: '03', title: '向量完整性', description: '区分缺失向量、维度不一致与不支持的索引后端。' },
    ],
  },
  performance: {
    title: '尚未运行性能门禁',
    description: '检查全局 API 响应与基线差异。',
    stepsHeading: '性能检查维度',
    steps: [
      { index: '01', title: '接口可用性', description: '核对 health、ready 与 meta 接口的成功次数。' },
      { index: '02', title: '耗时与吞吐', description: '逐项查看 P50、P95、P99 和 QPS 读数。' },
      { index: '03', title: '基线与门禁结论', description: '读取实际退化比较与严格门禁结论，缺失时不推断通过。' },
    ],
  },
}

export function DiagnosticEmpty({
  kind,
  controller: c,
}: {
  kind: keyof typeof guides
  controller: DiagnosticsController
}) {
  const Icon = kind === 'retrieval' ? Search : kind === 'drift' ? BarChart3 : ShieldCheck
  return (
    <SplitEmptyStudio
      className={styles.emptyStudio}
      illustration={<Icon />}
      {...guides[kind]}
      shortcuts={
        kind === 'retrieval'
          ? [
              {
                key: 'drift',
                icon: <BarChart3 />,
                title: '向量漂移检查',
                description: '比较向量样本与距离阈值',
                onClick: () => c.setTab('drift'),
              },
              {
                key: 'performance',
                icon: <ShieldCheck />,
                title: '性能门禁压测',
                description: '核对全局接口耗时与基线',
                onClick: () => c.setTab('performance'),
              },
            ]
          : undefined
      }
    />
  )
}
