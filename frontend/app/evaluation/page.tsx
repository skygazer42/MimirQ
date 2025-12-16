'use client'

import { useState } from 'react'
import {
  BarChart3,
  BookOpen,
  CheckCircle,
  ChevronRight,
  FileText,
  LayoutDashboard,
  Loader2,
  Play,
  RefreshCw,
  Settings2,
  Target,
  AlertCircle,
  ArrowRight,
  TrendingUp,
  Microscope
} from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  Cell
} from 'recharts'

import { Navbar } from '@/components/navbar'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'

// 模拟数据
const MOCK_METRICS = [
  { id: 'faithfulness', name: 'Faithfulness', description: '回答是否忠实于上下文', category: 'Generation' },
  { id: 'answer_relevance', name: 'Answer Relevance', description: '回答是否切题', category: 'Generation' },
  { id: 'context_precision', name: 'Context Precision', description: '检索内容的精确度', category: 'Retrieval' },
  { id: 'context_recall', name: 'Context Recall', description: '检索内容的召回率', category: 'Retrieval' },
  { id: 'context_entity_recall', name: 'Context Entity Recall', description: '实体检索召回率', category: 'Retrieval' },
  { id: 'answer_similarity', name: 'Answer Semantic Similarity', description: '回答语义相似度', category: 'Generation' },
  { id: 'answer_correctness', name: 'Answer Correctness', description: '回答准确性 (vs Ground Truth)', category: 'Generation' },
]

const MOCK_RESULTS = [
  { subject: 'Faithfulness', A: 0.85, fullMark: 1 },
  { subject: 'Answer Relevance', A: 0.92, fullMark: 1 },
  { subject: 'Context Precision', A: 0.78, fullMark: 1 },
  { subject: 'Context Recall', A: 0.88, fullMark: 1 },
  { subject: 'Answer Correctness', A: 0.82, fullMark: 1 },
]

const MOCK_DETAILS = [
  {
    id: 1,
    question: "什么是 RAG 架构？",
    answer: "RAG (Retrieval-Augmented Generation) 是一种结合了检索和生成的架构...",
    context: "RAG 架构通过检索外部知识库来增强大语言模型的能力...",
    ground_truth: "RAG 是一种通过检索外部数据增强 LLM 的技术。",
    scores: { faithfulness: 0.9, answer_relevance: 0.95, context_recall: 1.0 }
  },
  {
    id: 2,
    question: "MimirQ 支持哪些文件格式？",
    answer: "支持 PDF 和 TXT。",
    context: "MimirQ 目前支持 PDF, Markdown, TXT, Excel 等多种格式...",
    ground_truth: "PDF, TXT, Markdown, Excel, Word.",
    scores: { faithfulness: 1.0, answer_relevance: 0.8, context_recall: 0.4 }
  },
  {
    id: 3,
    question: "如何部署该项目？",
    answer: "使用 Docker Compose。",
    context: "项目支持 Docker 容器化部署，运行 docker-compose up -d 即可...",
    ground_truth: "使用 Docker Compose 一键部署。",
    scores: { faithfulness: 1.0, answer_relevance: 1.0, context_recall: 1.0 }
  },
  {
    id: 4,
    question: "Milvus 的作用是什么？",
    answer: "Milvus 是一个向量数据库，用于存储和检索向量数据。",
    context: "后端使用 Milvus 作为向量搜索引擎...",
    ground_truth: "作为向量数据库存储 Embedding。",
    scores: { faithfulness: 0.95, answer_relevance: 0.9, context_recall: 0.9 }
  },
]

export default function EvaluationPage() {
  const [step, setStep] = useState<'config' | 'running' | 'result'>('config')
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>(['faithfulness', 'answer_relevance', 'context_precision', 'context_recall'])
  const [progress, setProgress] = useState(0)

  const toggleMetric = (id: string) => {
    setSelectedMetrics(prev =>
      prev.includes(id) ? prev.filter(m => m !== id) : [...prev, id]
    )
  }

  const startEvaluation = () => {
    setStep('running')
    setProgress(0)
    
    // 模拟进度
    const interval = setInterval(() => {
      setProgress(prev => {
        if (prev >= 100) {
          clearInterval(interval)
          setStep('result')
          return 100
        }
        return prev + 5
      })
    }, 150)
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50/50 dark:bg-slate-950 transition-colors duration-300">
      <Navbar />

      <main className="flex-1 flex flex-col overflow-hidden relative">
        {/* 背景装饰 */}
        <div className="absolute top-0 left-0 right-0 h-64 bg-gradient-to-b from-indigo-50/50 dark:from-indigo-900/10 to-transparent pointer-events-none" />

        {/* 顶部标题栏 */}
        <header className="px-8 py-6 flex-shrink-0 z-10">
          <div className="flex items-center gap-4 mb-6">
            <div className="w-12 h-12 bg-white dark:bg-slate-900 rounded-2xl flex items-center justify-center shadow-sm border border-slate-100 dark:border-slate-800">
              <BarChart3 className="w-6 h-6 text-indigo-600 dark:text-indigo-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">RAG 评估与对齐</h1>
              <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                基于 Ragas 框架，全方位评估知识库检索质量与回答准确性
              </p>
            </div>
          </div>
        </header>

        {/* 内容区域 */}
        <div className="flex-1 overflow-y-auto px-8 pb-8 scroll-smooth">
          <div className="max-w-6xl mx-auto space-y-6">
            
            {/* 配置视图 */}
            {step === 'config' && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
                {/* 左侧：测试集配置 */}
                <div className="lg:col-span-2 space-y-6">
                  <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm">
                    <h3 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2 mb-4">
                      <BookOpen className="w-5 h-5 text-indigo-500" />
                      测试集来源
                    </h3>
                    
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                      <div className="border-2 border-indigo-600 bg-indigo-50/30 dark:bg-indigo-900/10 rounded-xl p-4 cursor-pointer relative">
                        <div className="absolute top-3 right-3 text-indigo-600">
                          <CheckCircle className="w-5 h-5" />
                        </div>
                        <div className="font-semibold text-slate-900 dark:text-white mb-1">自动生成</div>
                        <p className="text-xs text-slate-500 dark:text-slate-400">基于现有知识库文档，使用 LLM 自动构建问答对 (Ground Truth)</p>
                      </div>
                      <div className="border-2 border-slate-100 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 rounded-xl p-4 cursor-pointer transition-all">
                        <div className="font-semibold text-slate-900 dark:text-white mb-1">手动上传</div>
                        <p className="text-xs text-slate-500 dark:text-slate-400">上传包含 question, answer, ground_truth 的 CSV/JSON 文件</p>
                      </div>
                    </div>

                    <div className="space-y-4">
                      <div className="space-y-2">
                         <label className="text-sm font-medium text-slate-700 dark:text-slate-300">选择知识库集合</label>
                         <select className="w-full h-10 rounded-lg border border-slate-200 dark:border-slate-800 bg-transparent px-3 text-sm outline-none focus:border-indigo-500 dark:text-slate-200">
                           <option>默认知识库 (Default Collection)</option>
                           <option>产品手册 (Product Manuals)</option>
                           <option>技术文档 (Tech Docs)</option>
                         </select>
                      </div>
                      <div className="space-y-2">
                         <label className="text-sm font-medium text-slate-700 dark:text-slate-300">生成数量</label>
                         <div className="flex items-center gap-4">
                           <input type="range" min="5" max="50" step="5" defaultValue="10" className="flex-1 h-2 bg-slate-100 dark:bg-slate-800 rounded-lg appearance-none cursor-pointer accent-indigo-600" />
                           <span className="text-sm font-mono text-indigo-600 font-bold w-8">10</span>
                         </div>
                      </div>
                    </div>
                  </div>

                  <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm">
                    <h3 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2 mb-4">
                      <Target className="w-5 h-5 text-indigo-500" />
                      评估指标 (Metrics)
                    </h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {MOCK_METRICS.map(metric => (
                        <div 
                          key={metric.id}
                          onClick={() => toggleMetric(metric.id)}
                          className={cn(
                            "flex items-start gap-3 p-3 rounded-xl border transition-all cursor-pointer select-none",
                            selectedMetrics.includes(metric.id)
                              ? "bg-indigo-50 dark:bg-indigo-900/20 border-indigo-200 dark:border-indigo-800"
                              : "bg-white dark:bg-slate-900 border-slate-100 dark:border-slate-800 hover:border-slate-300"
                          )}
                        >
                          <div className={cn(
                            "w-4 h-4 rounded mt-0.5 border flex items-center justify-center transition-colors",
                            selectedMetrics.includes(metric.id) ? "bg-indigo-600 border-indigo-600" : "border-slate-300"
                          )}>
                             {selectedMetrics.includes(metric.id) && <CheckCircle className="w-3 h-3 text-white" />}
                          </div>
                          <div>
                            <div className="text-sm font-semibold text-slate-900 dark:text-white">{metric.name}</div>
                            <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{metric.description}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* 右侧：LLM 配置 */}
                <div className="space-y-6">
                  <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm">
                    <h3 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2 mb-4">
                      <Settings2 className="w-5 h-5 text-indigo-500" />
                      评测模型配置
                    </h3>
                    <div className="space-y-4">
                      <div className="p-3 bg-slate-50 dark:bg-slate-800 rounded-lg text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
                        Ragas 使用 LLM 作为裁判 (LLM-as-a-Judge) 来评估生成质量。建议使用 GPT-4 或同等水平模型以获得最准确的评分。
                      </div>
                      
                      <div className="space-y-2">
                         <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Judge Model</label>
                         <select className="w-full h-10 rounded-lg border border-slate-200 dark:border-slate-800 bg-transparent px-3 text-sm outline-none focus:border-indigo-500 dark:text-slate-200">
                           <option>gpt-4-turbo</option>
                           <option>gpt-3.5-turbo</option>
                           <option>gemini-pro</option>
                         </select>
                      </div>

                      <div className="space-y-2">
                         <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Critic Model (Optional)</label>
                         <select className="w-full h-10 rounded-lg border border-slate-200 dark:border-slate-800 bg-transparent px-3 text-sm outline-none focus:border-indigo-500 dark:text-slate-200">
                           <option>Same as Judge</option>
                           <option>gpt-4</option>
                         </select>
                      </div>
                    </div>
                  </div>

                  <Button 
                    size="lg" 
                    className="w-full h-14 text-lg font-bold bg-indigo-600 hover:bg-indigo-700 text-white shadow-xl shadow-indigo-200 dark:shadow-indigo-900/20 rounded-xl"
                    onClick={startEvaluation}
                  >
                    <Play className="w-5 h-5 mr-2 fill-current" />
                    开始评估
                  </Button>
                </div>
              </div>
            )}

            {/* 运行视图 */}
            {step === 'running' && (
              <div className="flex flex-col items-center justify-center min-h-[50vh] animate-in fade-in zoom-in-95 duration-500">
                 <div className="relative w-32 h-32 mb-8">
                   <div className="absolute inset-0 border-4 border-slate-100 dark:border-slate-800 rounded-full"></div>
                   <div className="absolute inset-0 border-4 border-indigo-600 rounded-full border-t-transparent animate-spin"></div>
                   <div className="absolute inset-0 flex items-center justify-center">
                     <span className="text-2xl font-bold text-indigo-600 dark:text-indigo-400">{progress}%</span>
                   </div>
                 </div>
                 <h2 className="text-2xl font-bold text-slate-900 dark:text-white mb-2">正在进行 RAG 评估...</h2>
                 <p className="text-slate-500 dark:text-slate-400 text-center max-w-md">
                   正在生成测试问题，检索上下文，并使用 LLM 计算各项指标得分。请耐心等待。
                 </p>
                 
                 <div className="grid grid-cols-3 gap-8 mt-12 w-full max-w-2xl text-center">
                    <div className="space-y-2">
                      <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">生成测试集</div>
                      <div className={cn("text-sm font-medium", progress > 20 ? "text-emerald-500" : "text-slate-500")}>
                        {progress > 20 ? "已完成" : "处理中..."}
                      </div>
                    </div>
                    <div className="space-y-2">
                      <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">RAG 检索回答</div>
                      <div className={cn("text-sm font-medium", progress > 50 ? "text-emerald-500" : "text-slate-500")}>
                        {progress > 50 ? "已完成" : (progress > 20 ? "处理中..." : "等待")}
                      </div>
                    </div>
                    <div className="space-y-2">
                      <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">计算指标</div>
                      <div className={cn("text-sm font-medium", progress > 90 ? "text-emerald-500" : "text-slate-500")}>
                        {progress > 90 ? "已完成" : (progress > 50 ? "处理中..." : "等待")}
                      </div>
                    </div>
                 </div>
              </div>
            )}

            {/* 结果视图 */}
            {step === 'result' && (
              <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                
                <div className="flex items-center justify-between">
                  <h2 className="text-2xl font-bold text-slate-900 dark:text-white">评估报告</h2>
                  <div className="flex gap-3">
                    <Button variant="outline" onClick={() => setStep('config')}>
                      <RefreshCw className="w-4 h-4 mr-2" />
                      重新评估
                    </Button>
                    <Button className="bg-indigo-600 hover:bg-indigo-700 text-white">
                      导出报告
                    </Button>
                  </div>
                </div>

                {/* 图表区域 */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                   {/* 雷达图 */}
                   <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm min-h-[400px] flex flex-col">
                      <h3 className="font-bold text-slate-900 dark:text-white mb-6 flex items-center gap-2">
                        <Target className="w-5 h-5 text-indigo-500" />
                        综合能力雷达图
                      </h3>
                      <div className="flex-1 w-full h-full min-h-[300px]">
                        <ResponsiveContainer width="100%" height="100%">
                          <RadarChart cx="50%" cy="50%" outerRadius="70%" data={MOCK_RESULTS}>
                            <PolarGrid stroke="#94a3b8" strokeOpacity={0.2} />
                            <PolarAngleAxis dataKey="subject" tick={{ fill: '#64748b', fontSize: 12 }} />
                            <PolarRadiusAxis angle={30} domain={[0, 1]} tick={false} axisLine={false} />
                            <Radar
                              name="MimirQ RAG"
                              dataKey="A"
                              stroke="#4f46e5"
                              strokeWidth={3}
                              fill="#4f46e5"
                              fillOpacity={0.2}
                            />
                            <Tooltip 
                              contentStyle={{ 
                                borderRadius: '12px', 
                                border: 'none', 
                                boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1)',
                                backgroundColor: 'rgba(255, 255, 255, 0.9)',
                                color: '#1e293b'
                              }}
                              itemStyle={{ color: '#4f46e5' }}
                            />
                          </RadarChart>
                        </ResponsiveContainer>
                      </div>
                   </div>

                   {/* 核心指标卡片 */}
                   <div className="space-y-6">
                      <StatsGrid className="lg:grid-cols-2">
                         <StatCard icon={TrendingUp} label="Ragas 总分" value="0.85" color="indigo" />
                         <StatCard icon={CheckCircle} label="测试样本数" value="10" color="blue" />
                      </StatsGrid>
                      
                      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm flex-1">
                         <h3 className="font-bold text-slate-900 dark:text-white mb-4">指标分析</h3>
                         <div className="space-y-4">
                           {MOCK_RESULTS.map((item) => (
                             <div key={item.subject}>
                               <div className="flex justify-between text-sm mb-1.5">
                                 <span className="font-medium text-slate-700 dark:text-slate-300">{item.subject}</span>
                                 <span className="font-mono font-bold text-indigo-600">{item.A.toFixed(2)}</span>
                               </div>
                               <div className="h-2.5 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                                 <div 
                                   className={cn(
                                     "h-full rounded-full transition-all duration-1000",
                                     item.A > 0.8 ? "bg-emerald-500" : item.A > 0.6 ? "bg-amber-500" : "bg-red-500"
                                   )}
                                   style={{ width: `${item.A * 100}%` }}
                                 />
                               </div>
                             </div>
                           ))}
                         </div>
                      </div>
                   </div>
                </div>

                {/* 详细表格 */}
                <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
                  <div className="p-6 border-b border-slate-100 dark:border-slate-800 flex justify-between items-center">
                    <h3 className="font-bold text-slate-900 dark:text-white flex items-center gap-2">
                      <Microscope className="w-5 h-5 text-indigo-500" />
                      详细评估记录
                    </h3>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm text-left">
                      <thead className="text-xs text-slate-500 dark:text-slate-400 uppercase bg-slate-50 dark:bg-slate-800/50">
                        <tr>
                          <th className="px-6 py-4">ID</th>
                          <th className="px-6 py-4 w-1/3">问题 & 回答</th>
                          <th className="px-6 py-4 w-1/3">检索上下文 (Context)</th>
                          <th className="px-6 py-4">Scores</th>
                          <th className="px-6 py-4">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                        {MOCK_DETAILS.map((row) => (
                          <tr key={row.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors">
                            <td className="px-6 py-4 font-mono text-slate-400">{row.id}</td>
                            <td className="px-6 py-4">
                              <div className="space-y-2">
                                <p className="font-semibold text-slate-900 dark:text-slate-200">{row.question}</p>
                                <p className="text-slate-600 dark:text-slate-400 line-clamp-2 bg-slate-50 dark:bg-slate-800 p-2 rounded-md border border-slate-100 dark:border-slate-700">{row.answer}</p>
                              </div>
                            </td>
                            <td className="px-6 py-4">
                              <p className="text-slate-500 dark:text-slate-400 line-clamp-3 text-xs leading-relaxed italic">
                                "{row.context}"
                              </p>
                            </td>
                            <td className="px-6 py-4">
                              <div className="space-y-1.5">
                                {Object.entries(row.scores).map(([key, score]) => (
                                  <div key={key} className="flex items-center justify-between gap-4 text-xs">
                                    <span className="text-slate-500 capitalize">{key.replace('_', ' ')}</span>
                                    <span className={cn(
                                      "font-mono font-bold",
                                      score > 0.8 ? "text-emerald-600" : score > 0.5 ? "text-amber-600" : "text-red-600"
                                    )}>{score}</span>
                                  </div>
                                ))}
                              </div>
                            </td>
                            <td className="px-6 py-4">
                              {row.scores.context_recall < 0.5 ? (
                                <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-red-50 text-red-600 border border-red-100">
                                  <AlertCircle className="w-3 h-3" />
                                  Low Recall
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-600 border border-emerald-100">
                                  <CheckCircle className="w-3 h-3" />
                                  Pass
                                </span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

              </div>
            )}

          </div>
        </div>
      </main>
    </div>
  )
}

