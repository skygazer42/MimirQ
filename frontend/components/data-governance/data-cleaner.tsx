/**
 * 数据清洗组件
 * 功能：去除特殊字符、统一标点、去除多余空格、乱码修复
 */
'use client'

import { useState, useCallback, useMemo } from 'react'
import {
  Wrench,
  Sparkles,
  Check,
  Undo,
  Eraser,
  Replace,
  AlignLeft,
  TextCursorInput,
  Hash,
  Scissors,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface DataCleanerProps {
  content: string
  cleanedContent?: string
  onClean: (cleaned: string) => void
}

// 清洗规则
const CLEAN_RULES = [
  {
    id: 'extra-spaces',
    label: '去除多余空格',
    description: '删除行内多余空格和段落间多余空行',
    icon: Eraser,
    defaultEnabled: true,
  },
  {
    id: 'special-chars',
    label: '去除控制字符',
    description: '删除不可见的控制字符（0x00-0x1F）',
    icon: Hash,
    defaultEnabled: true,
  },
  {
    id: 'unify-punctuation',
    label: '统一中文标点',
    description: '将英文标点转换为中文标点',
    icon: Replace,
    defaultEnabled: false,
  },
  {
    id: 'fix-newlines',
    label: '修复换行',
    description: '删除行尾空格，统一换行符',
    icon: AlignLeft,
    defaultEnabled: true,
  },
  {
    id: 'trim-content',
    label: '首尾去空',
    description: '删除文档首尾的空白字符',
    icon: Scissors,
    defaultEnabled: true,
  },
] as const

type CleanRuleId = typeof CLEAN_RULES[number]['id']

export function DataCleaner({ content, cleanedContent = '', onClean }: DataCleanerProps) {
  const [enabledRules, setEnabledRules] = useState<Set<CleanRuleId>>(
    new Set(CLEAN_RULES.filter((r) => r.defaultEnabled).map((r) => r.id))
  )
  const [previewDiff, setPreviewDiff] = useState(false)

  // 计算清洗后的内容
  const cleaned = useMemo(() => {
    let result = cleanedContent || content

    if (!cleanedContent) {
      // 如果没有传入清洗后的内容，根据规则实时计算
      if (enabledRules.has('extra-spaces')) {
        result = result
          .replace(/[ \t]+/g, ' ')  // 多个空格/制表符替换为单个空格
          .replace(/\n{3,}/g, '\n\n')  // 多个空行替换为两个
          .replace(/^[ \t]+/gm, '')  // 删除行首空格
      }

      if (enabledRules.has('special-chars')) {
        result = result.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
      }

      if (enabledRules.has('unify-punctuation')) {
        result = result
          .replace(/,/g, '，')
          .replace(/\./g, '。')
          .replace(/!/g, '！')
          .replace(/\?/g, '？')
          .replace(/:/g, '：')
          .replace(/;/g, '；')
          .replace(/\(/g, '（')
          .replace(/\)/g, '）')
      }

      if (enabledRules.has('fix-newlines')) {
        result = result
          .replace(/[ \t]+\n/g, '\n')  // 删除行尾空格
          .replace(/\r\n/g, '\n')  // 统一换行符
          .replace(/\r/g, '\n')
      }

      if (enabledRules.has('trim-content')) {
        result = result.trim()
      }
    }

    return result
  }, [content, cleanedContent, enabledRules])

  // 计算变化统计
  const stats = useMemo(() => {
    const originalLength = content.length
    const cleanedLength = cleaned.length
    const removed = originalLength - cleanedLength
    const ratio = originalLength > 0 ? ((removed / originalLength) * 100).toFixed(1) : '0.0'

    // 计算删除的空格数量
    const originalSpaces = (content.match(/[ \t]/g) || []).length
    const cleanedSpaces = (cleaned.match(/[ \t]/g) || []).length
    const removedSpaces = originalSpaces - cleanedSpaces

    // 计算删除的空行数量
    const originalEmptyLines = (content.match(/\n\n+/g) || []).length
    const cleanedEmptyLines = (cleaned.match(/\n\n+/g) || []).length
    const removedEmptyLines = originalEmptyLines - cleanedEmptyLines

    return {
      originalLength,
      cleanedLength,
      removed,
      ratio,
      removedSpaces,
      removedEmptyLines,
    }
  }, [content, cleaned])

  // 切换规则
  const toggleRule = useCallback((ruleId: CleanRuleId) => {
    setEnabledRules((prev) => {
      const next = new Set(prev)
      if (next.has(ruleId)) {
        next.delete(ruleId)
      } else {
        next.add(ruleId)
      }
      return next
    })
    // 清除已保存的清洗内容，使用规则重新计算
    onClean('')
  }, [onClean])

  // 应用清洗
  const handleApply = useCallback(() => {
    onClean(cleaned)
  }, [cleaned, onClean])

  // 重置
  const handleReset = useCallback(() => {
    setEnabledRules(new Set(CLEAN_RULES.filter((r) => r.defaultEnabled).map((r) => r.id)))
    onClean(content)
  }, [onClean, content])

  // 全选/全不选
  const handleToggleAll = useCallback(() => {
    if (enabledRules.size === CLEAN_RULES.length) {
      setEnabledRules(new Set())
    } else {
      setEnabledRules(new Set(CLEAN_RULES.map((r) => r.id)))
    }
  }, [enabledRules.size])

  const hasChanges = cleaned !== content
  const allSelected = enabledRules.size === CLEAN_RULES.length

  return (
    <div className="p-6 space-y-6">
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wrench className="w-5 h-5 text-green-600" />
          <h3 className="font-bold text-gray-900">智能清洗</h3>
        </div>
        <Button variant="ghost" size="sm" onClick={handleToggleAll} className="text-xs">
          {allSelected ? '全不选' : '全选'}
        </Button>
      </div>

      {/* 快速预览统计 */}
      {hasChanges && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <Sparkles className="w-4 h-4 text-green-600" />
            <span className="text-sm font-medium text-green-700">预览效果</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-green-600">原始长度</div>
              <div className="text-lg font-bold text-green-900">{stats.originalLength.toLocaleString()}</div>
            </div>
            <div>
              <div className="text-xs text-green-600">清洗后</div>
              <div className="text-lg font-bold text-green-900">{stats.cleanedLength.toLocaleString()}</div>
            </div>
          </div>
          <div className="mt-3 pt-3 border-t border-green-200">
            <div className="text-xs text-green-600">
              将删除 <span className="font-bold">{stats.removed.toLocaleString()}</span> 个字符
              <span className="text-green-500"> ({stats.ratio}%)</span>
            </div>
          </div>
        </div>
      )}

      {/* 清洗规则列表 */}
      <div className="space-y-2">
        {CLEAN_RULES.map((rule) => {
          const Icon = rule.icon
          const isEnabled = enabledRules.has(rule.id)

          return (
            <button
              key={rule.id}
              onClick={() => toggleRule(rule.id)}
              className={cn(
                "w-full flex items-start gap-3 p-3 rounded-xl border transition-all text-left",
                isEnabled
                  ? "bg-green-50 border-green-200 hover:bg-green-100"
                  : "bg-gray-50 border-gray-200 hover:bg-gray-100"
              )}
            >
              <div className={cn(
                "w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 mt-0.5 transition-colors",
                isEnabled
                  ? "bg-green-500 border-green-500"
                  : "border-gray-300 bg-white"
              )}>
                {isEnabled && <Check className="w-3 h-3 text-white" />}
              </div>
              <div className="w-8 h-8 rounded-lg bg-white flex items-center justify-center flex-shrink-0">
                <Icon className={cn("w-4 h-4", isEnabled ? "text-green-600" : "text-gray-400")} />
              </div>
              <div className="flex-1 min-w-0">
                <div className={cn(
                  "text-sm font-medium",
                  isEnabled ? "text-green-900" : "text-gray-700"
                )}>
                  {rule.label}
                </div>
                <div className={cn(
                  "text-xs mt-0.5",
                  isEnabled ? "text-green-600" : "text-gray-500"
                )}>
                  {rule.description}
                </div>
              </div>
            </button>
          )
        })}
      </div>

      {/* 操作按钮 */}
      <div className="flex items-center gap-2 pt-4 border-t border-gray-200">
        <Button
          onClick={handleReset}
          variant="outline"
          size="sm"
          className="flex-1 gap-1.5"
        >
          <Undo className="w-3.5 h-3.5" />
          重置
        </Button>
        <Button
          onClick={handleApply}
          disabled={!hasChanges}
          className="flex-1 gap-2 bg-green-600 hover:bg-green-700"
        >
          <Sparkles className="w-4 h-4" />
          应用清洗
        </Button>
      </div>

      {/* 差异对比 */}
      {hasChanges && (
        <div className="border border-gray-200 rounded-xl overflow-hidden">
          <button
            onClick={() => setPreviewDiff(!previewDiff)}
            className="w-full flex items-center justify-between p-3 hover:bg-gray-50 transition-colors"
          >
            <span className="text-sm font-medium text-gray-700">差异对比</span>
            <TextCursorInput className="w-4 h-4 text-gray-400" />
          </button>
          {previewDiff && (
            <div className="p-4 border-t border-gray-200 bg-gray-50 max-h-60 overflow-y-auto">
              <div className="grid grid-cols-2 gap-4 text-xs font-mono">
                <div>
                  <div className="text-red-600 mb-2 font-medium">删除内容</div>
                  <div className="bg-red-50 p-2 rounded text-red-700 whitespace-pre-wrap break-all">
                    {content.split('').filter((c, i) => cleaned[i] !== c).join('') || '(无)'}
                  </div>
                </div>
                <div>
                  <div className="text-green-600 mb-2 font-medium">保留内容</div>
                  <div className="bg-green-50 p-2 rounded text-green-700 whitespace-pre-wrap break-all">
                    {cleaned || '(空)'}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
