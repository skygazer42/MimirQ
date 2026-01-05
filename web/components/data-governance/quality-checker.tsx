/**
 * 数据质量检测组件
 * 检测项：字符统计、语言检测、编码识别、格式验证、问题识别
 */
'use client'

import { useState, useCallback, useEffect, useMemo } from 'react'
import {
  ScanLine,
  Play,
  CheckCircle,
  AlertTriangle,
  Info,
  FileText,
  Hash,
  Languages,
  Code,
  List,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface QualityIssue {
  id: string
  type: 'error' | 'warning' | 'info'
  message: string
  position?: { start: number; end: number }
  fix?: () => void
}

interface QualityCheckerProps {
  content: string
  initialScore?: number
  initialIssues?: QualityIssue[]
  onComplete: (result: { score: number; issues: QualityIssue[] }) => void
}

// 质量检测项
const CHECK_ITEMS = [
  { id: 'chars', label: '字符统计', icon: FileText },
  { id: 'encoding', label: '编码检测', icon: Code },
  { id: 'language', label: '语言识别', icon: Languages },
  { id: 'format', label: '格式验证', icon: List },
  { id: 'issues', label: '问题识别', icon: AlertTriangle },
]

export function QualityChecker({ content, initialScore = 0, initialIssues = [], onComplete }: QualityCheckerProps) {
  const [isScanning, setIsScanning] = useState(false)
  const [score, setScore] = useState(initialScore)
  const [issues, setIssues] = useState<QualityIssue[]>(initialIssues)
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set(['chars']))
  const [scanProgress, setScanProgress] = useState(0)

  // 文本统计
  const textStats = useMemo(() => {
    const text = content || ''
    const chars = text.length
    const charsNoSpaces = text.replace(/\s/g, '').length
    const words = text.trim() ? text.trim().split(/\s+/).length : 0
    const lines = text.split('\n').length
    const paragraphs = text.split(/\n\n+/).filter((p) => p.trim()).length
    const chineseChars = (text.match(/[\u4e00-\u9fa5]/g) || []).length
    const englishWords = (text.match(/[a-zA-Z]+/g) || []).length
    const numbers = (text.match(/\d+/g) || []).length

    return {
      chars,
      charsNoSpaces,
      words,
      lines,
      paragraphs,
      chineseChars,
      englishWords,
      numbers,
    }
  }, [content])

  // 检测编码
  const encoding = useMemo(() => {
    // 简单检测
    const hasBOM = content.charCodeAt(0) === 0xFEFF
    const hasHighByte = [...content].some((c) => c.charCodeAt(0) > 255)
    if (hasBOM) return 'UTF-8 (BOM)'
    if (hasHighByte) return 'UTF-8'
    return 'ASCII'
  }, [content])

  // 检测语言
  const language = useMemo(() => {
    const chineseRatio = textStats.chineseChars / (textStats.chars || 1)
    const englishRatio = textStats.englishWords / (textStats.words || 1)

    if (chineseRatio > 0.3) return '中文 (简体)'
    if (englishRatio > 0.5) return 'English'
    return '混合语言'
  }, [textStats])

  // 格式检测
  const formatInfo = useMemo(() => {
    const hasMarkdown = /^#{1,6}\s|^\*{1,2}.*?\*{1,2}|^\[.*?\]\(.*?\)/m.test(content)
    const hasHtml = /<[^>]+>/.test(content)
    const hasHeaders = (content.match(/^#{1,6}\s/gm) || []).length
    const hasLists = (content.match(/^\s*[-*+]\s|^\s*\d+\.\s/gm) || []).length
    const hasTables = (content.match(/\|.*\|/g) || []).length > 0

    return {
      format: hasHtml ? 'HTML' : hasMarkdown ? 'Markdown' : '纯文本',
      hasHeaders,
      hasLists,
      hasTables,
    }
  }, [content])

  // 执行质量扫描
  const handleScan = useCallback(async () => {
    setIsScanning(true)
    setScanProgress(0)
    const detectedIssues: QualityIssue[] = []

    // 模拟扫描进度
    const steps = [
      { progress: 20, delay: 300 },
      { progress: 40, delay: 300 },
      { progress: 60, delay: 300 },
      { progress: 80, delay: 300 },
      { progress: 100, delay: 200 },
    ]

    for (const step of steps) {
      await new Promise((resolve) => setTimeout(resolve, step.delay))
      setScanProgress(step.progress)
    }

    // 问题检测
    // 1. 空段落
    const emptyParagraphs = (content.match(/\n\n+/g) || []).length
    if (emptyParagraphs > 5) {
      detectedIssues.push({
        id: 'empty-paragraphs',
        type: 'warning',
        message: `发现 ${emptyParagraphs} 处空段落，可能影响检索质量`,
      })
    }

    // 2. 过长段落
    const longParagraphs = content.split('\n\n').filter((p) => p.length > 1000)
    if (longParagraphs.length > 0) {
      detectedIssues.push({
        id: 'long-paragraphs',
        type: 'warning',
        message: `发现 ${longParagraphs.length} 处过长段落 (>1000字符)，建议切块`,
      })
    }

    // 3. 特殊字符
    const specialChars = (content.match(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g) || [])
    if (specialChars.length > 0) {
      detectedIssues.push({
        id: 'special-chars',
        type: 'error',
        message: `发现 ${specialChars.length} 个控制字符，可能导致解析错误`,
      })
    }

    // 4. 重复内容检测（简单版）
    const paragraphs = content.split('\n').filter((p) => p.trim().length > 20)
    const duplicates: string[] = []
    const seen = new Set<string>()
    for (const p of paragraphs) {
      const trimmed = p.trim().substring(0, 50)
      if (seen.has(trimmed)) {
        if (!duplicates.includes(trimmed)) duplicates.push(trimmed)
      }
      seen.add(trimmed)
    }
    if (duplicates.length > 0) {
      detectedIssues.push({
        id: 'duplicates',
        type: 'info',
        message: `发现 ${duplicates.length} 处可能的重复内容`,
      })
    }

    // 5. URL 检测
    const urls = content.match(/https?:\/\/[^\s]+/g) || []
    if (urls.length > 0) {
      detectedIssues.push({
        id: 'urls',
        type: 'info',
        message: `发现 ${urls.length} 个 URL 链接`,
      })
    }

    setIssues(detectedIssues)

    // 计算质量分数
    let calculatedScore = 100
    detectedIssues.forEach((issue) => {
      if (issue.type === 'error') calculatedScore -= 15
      if (issue.type === 'warning') calculatedScore -= 5
      if (issue.type === 'info') calculatedScore -= 1
    })
    calculatedScore = Math.max(0, calculatedScore)
    setScore(calculatedScore)

    // 自动展开问题区域
    if (detectedIssues.length > 0) {
      setExpandedItems((prev) => new Set([...prev, 'issues']))
    }

    setIsScanning(false)
    onComplete({ score: calculatedScore, issues: detectedIssues })
  }, [content, onComplete])

  // 切换展开
  const toggleExpanded = useCallback((id: string) => {
    setExpandedItems((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }, [])

  // 获取分数等级
  const scoreGrade = useMemo(() => {
    if (score >= 90) return { label: '优秀', color: 'green', bg: 'bg-green-100', text: 'text-green-700' }
    if (score >= 75) return { label: '良好', color: 'blue', bg: 'bg-blue-100', text: 'text-blue-700' }
    if (score >= 60) return { label: '及格', color: 'yellow', bg: 'bg-yellow-100', text: 'text-yellow-700' }
    return { label: '较差', color: 'red', bg: 'bg-red-100', text: 'text-red-700' }
  }, [score])

  // 初始自动扫描
  useEffect(() => {
    if (content && initialScore === 0) {
      handleScan()
    }
  }, [content, initialScore, handleScan])

  return (
    <div className="p-6 space-y-6">
      {/* 扫描按钮和分数展示 */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ScanLine className="w-5 h-5 text-blue-600" />
            <h3 className="font-bold text-gray-900">质量检测</h3>
          </div>
          <Button
            onClick={handleScan}
            disabled={isScanning}
            size="sm"
            className="gap-2"
          >
            {isScanning ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                扫描中 {scanProgress}%
              </>
            ) : (
              <>
                <Play className="w-4 h-4" />
                重新扫描
              </>
            )}
          </Button>
        </div>

        {/* 质量分数卡片 */}
        {score > 0 && (
          <div className={cn(
            "p-4 rounded-xl border-2 bg-gradient-to-br",
            scoreGrade.color === 'green' && "from-green-50 to-emerald-50 border-green-200",
            scoreGrade.color === 'blue' && "from-blue-50 to-indigo-50 border-blue-200",
            scoreGrade.color === 'yellow' && "from-yellow-50 to-amber-50 border-yellow-200",
            scoreGrade.color === 'red' && "from-red-50 to-orange-50 border-red-200",
          )}>
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm text-gray-500 mb-1">数据质量评分</div>
                <div className="flex items-baseline gap-2">
                  <span className="text-4xl font-bold text-gray-900">{score}</span>
                  <span className="text-sm text-gray-400">/ 100</span>
                  <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium", scoreGrade.bg, scoreGrade.text)}>
                    {scoreGrade.label}
                  </span>
                </div>
              </div>
              <div className={cn(
                "w-16 h-16 rounded-full flex items-center justify-center border-4",
                scoreGrade.color === 'green' && "border-green-300 bg-green-50",
                scoreGrade.color === 'blue' && "border-blue-300 bg-blue-50",
                scoreGrade.color === 'yellow' && "border-yellow-300 bg-yellow-50",
                scoreGrade.color === 'red' && "border-red-300 bg-red-50",
              )}>
                <span className={cn("text-2xl font-bold", scoreGrade.text)}>
                  {score}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 检测项列表 */}
      <div className="space-y-2">
        {CHECK_ITEMS.map((item) => {
          const Icon = item.icon
          const isExpanded = expandedItems.has(item.id)
          const issueCount = issues.filter((i) => i.type !== 'info').length

          return (
            <div
              key={item.id}
              className="border border-gray-200 rounded-xl overflow-hidden"
            >
              <button
                onClick={() => toggleExpanded(item.id)}
                className="w-full flex items-center justify-between p-3 hover:bg-gray-50 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center">
                    <Icon className="w-4 h-4 text-gray-600" />
                  </div>
                  <span className="text-sm font-medium text-gray-700">{item.label}</span>
                  {item.id === 'issues' && issueCount > 0 && (
                    <span className="text-xs bg-red-100 text-red-600 px-1.5 py-0.5 rounded-full">
                      {issueCount}
                    </span>
                  )}
                </div>
                {isExpanded ? (
                  <ChevronDown className="w-4 h-4 text-gray-400" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-gray-400" />
                )}
              </button>

              {isExpanded && (
                <div className="p-4 pt-0 border-t border-gray-100 bg-gray-50/50">
                  {item.id === 'chars' && (
                    <div className="grid grid-cols-2 gap-3">
                      <StatRow label="总字符数" value={textStats.chars.toLocaleString()} />
                      <StatRow label="不含空格" value={textStats.charsNoSpaces.toLocaleString()} />
                      <StatRow label="单词数" value={textStats.words.toLocaleString()} />
                      <StatRow label="行数" value={textStats.lines.toLocaleString()} />
                      <StatRow label="段落数" value={textStats.paragraphs.toLocaleString()} />
                      <StatRow label="中文字符" value={textStats.chineseChars.toLocaleString()} />
                      <StatRow label="英文单词" value={textStats.englishWords.toLocaleString()} />
                      <StatRow label="数字数量" value={textStats.numbers.toLocaleString()} />
                    </div>
                  )}

                  {item.id === 'encoding' && (
                    <div className="space-y-2">
                      <StatRow label="检测编码" value={encoding} />
                      <StatRow label="字符范围" value="基本多文种平面" />
                      <StatRow label="是否含BOM" value={content.charCodeAt(0) === 0xFEFF ? '是' : '否'} />
                    </div>
                  )}

                  {item.id === 'language' && (
                    <div className="space-y-2">
                      <StatRow label="主要语言" value={language} />
                      <StatRow label="中文占比" value={`${((textStats.chineseChars / (textStats.chars || 1)) * 100).toFixed(1)}%`} />
                      <StatRow label="英文占比" value={`${((textStats.englishWords / (textStats.words || 1)) * 100).toFixed(1)}%`} />
                    </div>
                  )}

                  {item.id === 'format' && (
                    <div className="space-y-2">
                      <StatRow label="文档格式" value={formatInfo.format} />
                      <StatRow label="标题数量" value={formatInfo.hasHeaders} />
                      <StatRow label="列表数量" value={formatInfo.hasLists} />
                      <StatRow label="包含表格" value={formatInfo.hasTables ? '是' : '否'} />
                    </div>
                  )}

                  {item.id === 'issues' && (
                    <div className="space-y-2">
                      {issues.length === 0 ? (
                        <div className="flex items-center gap-2 text-sm text-green-600 py-2">
                          <CheckCircle className="w-4 h-4" />
                          未发现明显问题
                        </div>
                      ) : (
                        issues.map((issue) => (
                          <div
                            key={issue.id}
                            className={cn(
                              "flex items-start gap-2 p-3 rounded-lg",
                              issue.type === 'error' && "bg-red-50 border border-red-100",
                              issue.type === 'warning' && "bg-yellow-50 border border-yellow-100",
                              issue.type === 'info' && "bg-blue-50 border border-blue-100",
                            )}
                          >
                            {issue.type === 'error' && <AlertTriangle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />}
                            {issue.type === 'warning' && <AlertTriangle className="w-4 h-4 text-yellow-600 flex-shrink-0 mt-0.5" />}
                            {issue.type === 'info' && <Info className="w-4 h-4 text-blue-500 flex-shrink-0 mt-0.5" />}
                            <span className={cn(
                              "text-sm",
                              issue.type === 'error' && "text-red-700",
                              issue.type === 'warning' && "text-yellow-700",
                              issue.type === 'info' && "text-blue-700",
                            )}>
                              {issue.message}
                            </span>
                          </div>
                        ))
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function StatRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-xs text-gray-500">{label}</span>
      <span className="text-sm font-medium text-gray-900">{value}</span>
    </div>
  )
}
