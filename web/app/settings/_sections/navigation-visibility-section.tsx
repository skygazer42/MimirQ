'use client'

import type { ComponentType } from 'react'
import { GitCompare, Hash, LineChart, Network, ScrollText, SlidersHorizontal, Wand2, Braces } from '@/components/icons'

import { SettingsSwitch } from '@/components/settings/settings-switch'
import {
  type AdminControlledNavigationModule,
  normalizeNavigationModules,
} from '@/lib/navigation-visibility'
import type { NavigationConfig } from '@/lib/api'
import styles from '../settings.module.css'

type NavigationVisibilitySectionProps = {
  navigation: NavigationConfig
  updateNavigation: (patch: Partial<NavigationConfig>) => void
}

const MODULE_GROUPS: Array<{
  title: string
  description: string
  items: Array<{
    key: AdminControlledNavigationModule
    label: string
    description: string
    icon: ComponentType<{ className?: string }>
  }>
}> = [
  {
    title: '入库治理',
    description: '清洗规则与重复内容',
    items: [
      {
        key: 'governanceProfiles',
        label: '治理配置',
        description: '管理清洗配置、规则包和治理脚本',
        icon: Braces,
      },
      {
        key: 'commonLines',
        label: '重复内容治理',
        description: '跨文档识别页眉、页脚和重复噪声',
        icon: Hash,
      },
    ],
  },
  {
    title: '图谱与评测',
    description: '知识关系与检索质量',
    items: [
      {
        key: 'knowledgeGraph',
        label: '知识图谱',
        description: '查看实体、事件和关系网络',
        icon: Network,
      },
      {
        key: 'graphSnapshots',
        label: '图谱快照',
        description: '对比图谱版本与节点变化',
        icon: GitCompare,
      },
      {
        key: 'graphDiagnostics',
        label: '图谱检索评测',
        description: '诊断图谱召回与检索难例',
        icon: ScrollText,
      },
      {
        key: 'ragas',
        label: 'RAGAS 评测',
        description: '评测对话质量与回归结果',
        icon: LineChart,
      },
      {
        key: 'ablations',
        label: '检索消融',
        description: '对比召回策略和参数组合',
        icon: SlidersHorizontal,
      },
    ],
  },
  {
    title: '资产运营',
    description: '报告与提示词模板',
    items: [
      {
        key: 'reports',
        label: '数据报告导出',
        description: '导出数据集质量和审计报告',
        icon: ScrollText,
      },
      {
        key: 'prompts',
        label: '提示词',
        description: '维护对话与知识图谱的提示词模板',
        icon: Wand2,
      },
    ],
  },
]

export function NavigationVisibilitySection({
  navigation,
  updateNavigation,
}: Readonly<NavigationVisibilitySectionProps>) {
  const visibleModules = normalizeNavigationModules(navigation.user_visible_modules)
  const visibleSet = new Set(visibleModules)

  const setModuleVisible = (key: AdminControlledNavigationModule, visible: boolean) => {
    const next = new Set(visibleModules)
    if (visible) next.add(key)
    else next.delete(key)
    updateNavigation({ user_visible_modules: normalizeNavigationModules(Array.from(next)) })
  }

  const renderModule = (item: (typeof MODULE_GROUPS)[number]['items'][number]) => {
    const Icon = item.icon
    return (
      <div key={item.key} className={styles.navigationRow}>
        <Icon className={styles.navigationIcon} />
        <div className={styles.navigationCopy}>
          <label htmlFor={`navigation-${item.key}`} className={styles.navigationLabel}>{item.label}</label>
          <p id={`navigation-${item.key}-description`} className={styles.navigationDescription}>{item.description}</p>
        </div>
        <SettingsSwitch id={`navigation-${item.key}`} aria-label={`普通用户显示${item.label}`} aria-describedby={`navigation-${item.key}-description`} checked={visibleSet.has(item.key)} onCheckedChange={(next) => setModuleVisible(item.key, next)} />
      </div>
    )
  }

  return (
    <div className={styles.navigationGroups}>
      {MODULE_GROUPS.map((group, index) => (
        <section key={group.title} aria-labelledby={`navigation-group-${index}`} className={styles.navigationGroup}>
          <header className={styles.navigationGroupHeader}>
            <h3 id={`navigation-group-${index}`} className={styles.navigationGroupTitle}>{group.title}</h3>
            <p className={styles.navigationDescription}>{group.description}</p>
          </header>
          <div className={styles.navigationItems}>{group.items.map(renderModule)}</div>
        </section>
      ))}
    </div>
  )
}
