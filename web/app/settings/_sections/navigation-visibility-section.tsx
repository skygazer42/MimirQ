'use client'

import type { ComponentType } from 'react'
import { Eye, GitCompare, Hash, HelpCircle, LineChart, Network, ScrollText, SlidersHorizontal, Wand2, Braces } from 'lucide-react'

import { SettingsSwitch } from '@/components/settings/settings-switch'
import {
  type AdminControlledNavigationModule,
  normalizeNavigationModules,
} from '@/lib/navigation-visibility'
import type { NavigationConfig } from '@/lib/api'
import { cn } from '@/lib/utils'

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
    description: '治理规则和重复内容治理入口，适合交付/数据治理人员开放',
    items: [
      {
        key: 'governanceProfiles',
        label: '治理配置',
        description: '管理清洗 Profiles、规则包和治理脚本',
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
    description: '知识图谱、图谱快照、评测和消融实验入口，默认建议只给高级用户',
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
        description: '诊断图谱检索召回和 hardcase',
        icon: ScrollText,
      },
      {
        key: 'ragas',
        label: 'RAGAS 评测',
        description: '运行对话/回归质量评测',
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
    description: '报告与提示词资产入口，适合运营或模型管理员按需开放',
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
        description: '维护对话和 KG 使用的模板资产',
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

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-[13px] font-semibold text-foreground">
            <Eye className="h-3.5 w-3.5 text-primary" />
            普通用户入口显示
            <span className="group/nav-entry-help relative inline-flex">
              <button
                type="button"
                aria-label="查看普通用户入口显示说明"
                className="inline-flex size-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/25"
              >
                <HelpCircle className="h-3.5 w-3.5" />
              </button>
              <span className="pointer-events-none absolute left-1/2 top-full z-30 mt-2 hidden w-[min(360px,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border border-primary/20 bg-popover px-3 py-2 text-[11px] font-medium leading-relaxed text-popover-foreground shadow-[0_14px_34px_hsl(var(--foreground)/0.14)] group-hover/nav-entry-help:block group-focus-within/nav-entry-help:block md:left-full md:top-1/2 md:mt-0 md:ml-2 md:-translate-x-0 md:-translate-y-1/2">
                管理员始终可见；这里通过后端 /settings 持久化普通用户左侧导航和直接访问页的入口策略
              </span>
            </span>
          </h2>
        </div>
      </div>

      <div className="rounded-[16px] border border-border/60 bg-card/82 p-3.5 shadow-sm">
        <div className="grid gap-3 xl:grid-cols-3">
          {MODULE_GROUPS.map((group) => (
            <div
              key={group.title}
              className="rounded-[14px] border border-border/60 bg-card/80 p-3 shadow-[0_8px_20px_hsl(var(--foreground)/0.025)]"
            >
              <div className="mb-2.5">
                <div className="text-[12px] font-semibold text-foreground">{group.title}</div>
                <div className="mt-0.5 text-[10.5px] font-medium leading-4 text-muted-foreground">{group.description}</div>
              </div>
              <div className="space-y-2">
                {group.items.map((item) => {
                  const Icon = item.icon
                  const checked = visibleSet.has(item.key)
                  return (
                    <div
                      key={item.key}
                      className={cn(
                        'flex items-center justify-between gap-3 rounded-[12px] border px-3 py-2 transition-colors',
                        checked
                          ? 'border-primary/25 bg-primary/10'
                          : 'border-border/60 bg-card hover:border-muted-foreground/30'
                      )}
                    >
                      <div className="flex min-w-0 items-center gap-2.5">
                        <span
                          className={cn(
                            'flex size-7 shrink-0 items-center justify-center rounded-[10px]',
                            checked ? 'bg-primary/12 text-primary' : 'bg-muted text-muted-foreground'
                          )}
                        >
                          <Icon className="size-3.5" />
                        </span>
                        <div className="min-w-0">
                          <div className="text-[12px] font-semibold text-foreground">{item.label}</div>
                          <div className="truncate text-[10.5px] font-medium leading-4 text-muted-foreground">
                            {item.description}
                          </div>
                        </div>
                      </div>
                      <SettingsSwitch
                        aria-label={`普通用户显示${item.label}`}
                        checked={checked}
                        onCheckedChange={(next) => setModuleVisible(item.key, next)}
                      />
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
