'use client'

import type { ComponentType } from 'react'
import { Eye, EyeOff, GitCompare, Hash, HelpCircle, LineChart, Network, ScrollText, SlidersHorizontal, Wand2, Braces } from 'lucide-react'

import { Switch } from '@/components/ui/switch'
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
    description: '治理规则和样板行发现入口，适合交付/数据治理人员开放。',
    items: [
      {
        key: 'governanceProfiles',
        label: '治理配置',
        description: '管理清洗 Profiles、规则包和治理脚本。',
        icon: Braces,
      },
      {
        key: 'commonLines',
        label: '样板行发现',
        description: '跨文档识别页眉、页脚和重复噪声。',
        icon: Hash,
      },
    ],
  },
  {
    title: '图谱与评测',
    description: '知识图谱、图谱快照、评测和消融实验入口，默认建议只给高级用户。',
    items: [
      {
        key: 'knowledgeGraph',
        label: '知识图谱',
        description: '查看实体、事件和关系网络。',
        icon: Network,
      },
      {
        key: 'graphSnapshots',
        label: '图谱快照',
        description: '对比图谱版本与节点变化。',
        icon: GitCompare,
      },
      {
        key: 'graphDiagnostics',
        label: '图谱检索评测',
        description: '诊断图谱检索召回和 hardcase。',
        icon: ScrollText,
      },
      {
        key: 'ragas',
        label: 'RAGAS 评测',
        description: '运行对话/回归质量评测。',
        icon: LineChart,
      },
      {
        key: 'ablations',
        label: '检索消融',
        description: '对比召回策略和参数组合。',
        icon: SlidersHorizontal,
      },
    ],
  },
  {
    title: '资产运营',
    description: '报告与提示词资产入口，适合运营或模型管理员按需开放。',
    items: [
      {
        key: 'reports',
        label: '数据报告导出',
        description: '导出数据集质量和审计报告。',
        icon: ScrollText,
      },
      {
        key: 'prompts',
        label: '提示词',
        description: '维护对话和 KG 使用的模板资产。',
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
          <h2 className="flex items-center gap-2 text-[13px] font-medium text-slate-950">
            <Eye className="h-3.5 w-3.5 text-blue-600" />
            普通用户入口显示
            <span className="group/nav-entry-help relative inline-flex">
              <button
                type="button"
                aria-label="查看普通用户入口显示说明"
                className="inline-flex size-5 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-blue-50 hover:text-blue-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-200"
              >
                <HelpCircle className="h-3.5 w-3.5" />
              </button>
              <span className="pointer-events-none absolute left-1/2 top-full z-30 mt-2 hidden w-[min(360px,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border border-blue-100 bg-white px-3 py-2 text-[11px] font-medium leading-relaxed text-slate-600 shadow-[0_14px_34px_rgba(15,23,42,0.14)] group-hover/nav-entry-help:block group-focus-within/nav-entry-help:block md:left-full md:top-1/2 md:mt-0 md:ml-2 md:-translate-x-0 md:-translate-y-1/2">
                管理员始终可见；这里控制普通用户左侧导航和直接访问页的前端入口。
              </span>
            </span>
          </h2>
        </div>
        <div className="rounded-full border border-blue-100 bg-blue-50 px-2.5 py-1 text-[11px] font-medium text-blue-600">
          后端 /settings
        </div>
      </div>

      <div className="rounded-[16px] border border-slate-200/75 bg-card p-3.5 shadow-sm">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-[13px] border border-slate-200 bg-slate-50/60 px-3 py-2">
          <div className="flex min-w-0 items-center gap-2">
            {visibleModules.length > 0 ? (
              <Eye className="size-4 text-emerald-600" />
            ) : (
              <EyeOff className="size-4 text-slate-500" />
            )}
            <span className="text-[12px] font-medium text-slate-800">
              普通用户已开放 {visibleModules.length} 个高级入口
            </span>
          </div>
          <span className="text-[11px] text-slate-500">
            接口权限仍由后端 RBAC / 路由鉴权控制
          </span>
        </div>

        <div className="grid gap-3 xl:grid-cols-3">
          {MODULE_GROUPS.map((group) => (
            <div
              key={group.title}
              className="rounded-[14px] border border-slate-200 bg-white/80 p-3 shadow-[0_8px_20px_rgba(15,23,42,0.025)]"
            >
              <div className="mb-2.5">
                <div className="text-[12px] font-semibold text-slate-950">{group.title}</div>
                <div className="mt-0.5 text-[10.5px] leading-4 text-slate-500">{group.description}</div>
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
                          ? 'border-blue-200 bg-blue-50/55'
                          : 'border-slate-200 bg-card hover:border-slate-300'
                      )}
                    >
                      <div className="flex min-w-0 items-center gap-2.5">
                        <span
                          className={cn(
                            'flex size-7 shrink-0 items-center justify-center rounded-[10px]',
                            checked ? 'bg-blue-100 text-blue-600' : 'bg-slate-100 text-slate-500'
                          )}
                        >
                          <Icon className="size-3.5" />
                        </span>
                        <div className="min-w-0">
                          <div className="text-[12px] font-medium text-slate-900">{item.label}</div>
                          <div className="truncate text-[10.5px] leading-4 text-slate-500">
                            {item.description}
                          </div>
                        </div>
                      </div>
                      <Switch
                        aria-label={`普通用户显示${item.label}`}
                        checked={checked}
                        onCheckedChange={(next) => setModuleVisible(item.key, next)}
                        className="data-[state=checked]:bg-blue-600 data-[state=unchecked]:bg-slate-300"
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
