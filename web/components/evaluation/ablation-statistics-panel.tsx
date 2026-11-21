'use client'

import { FlaskConical } from '@/components/icons'
import { WorkspaceTableScroll } from '@/components/ui/operational-workspace'
import { cn } from '@/lib/utils'
import type { RagasRegressionRunDiffResponse } from '@/types'

export function AblationStatisticsPanel({
  diff,
}: Readonly<{
  diff: RagasRegressionRunDiffResponse | null
}>) {
  const rows = diff?.significance

  return (
    <section className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <FlaskConical className="size-4 text-success" />
            统计显著性审查
          </h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            展示本次对比返回的配对样本数、Bootstrap 95% 置信区间和 p 值。显著性结论使用服务端 BH 校正结果。
          </p>
        </div>
        <div className="rounded-full border border-warning/30 bg-warning/10 px-2.5 py-1 text-[11px] font-medium text-warning">
          Bootstrap CI / p-value / BH 校正
        </div>
      </div>

      {rows && rows.length > 0 ? (
        <div className="mt-3 overflow-hidden rounded-xl border border-border">
          <WorkspaceTableScroll label="运行指标显著性检验">
            <table className="w-full min-w-[780px] text-xs">
              <caption className="sr-only">本次运行对比的真实配对检验和 BH 校正结论</caption>
              <thead className="bg-muted/50 text-[11px] text-muted-foreground">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left">
                    指标
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    配对样本
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    均值变化
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Bootstrap 95% CI
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    p 值
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    BH 校正 p 值
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    结论
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.key} className="border-t border-border/50">
                    <th scope="row" className="px-3 py-2 text-left font-mono font-normal">
                      {row.key}
                    </th>
                    <td className="px-3 py-2 text-right font-mono">{row.compared}</td>
                    <td
                      className={cn(
                        'px-3 py-2 text-right font-mono text-muted-foreground',
                        row.delta_mean !== null && row.delta_mean > 0 && 'text-success',
                        row.delta_mean !== null && row.delta_mean < 0 && 'text-destructive',
                      )}
                    >
                      {row.delta_mean === null ? '未提供' : row.delta_mean.toFixed(4)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-muted-foreground">
                      {row.bootstrap_ci_low === null || row.bootstrap_ci_high === null
                        ? '未提供'
                        : `[${row.bootstrap_ci_low.toFixed(3)}, ${row.bootstrap_ci_high.toFixed(3)}]`}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-muted-foreground">
                      {row.p_value === null ? '未提供' : row.p_value.toFixed(4)}
                      {row.p_value_method !== null ? (
                        <span className="mt-1 block text-[10px]">{row.p_value_method}</span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-muted-foreground">
                      {row.p_value_bh === null ? '未提供' : row.p_value_bh.toFixed(4)}
                    </td>
                    <td className="px-3 py-2 text-right font-medium">
                      {row.p_value_bh === null ? '未提供检验结论' : row.significant ? '显著' : '未达显著'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </WorkspaceTableScroll>
        </div>
      ) : (
        <p className="mt-3 px-3 py-8 text-center text-xs text-muted-foreground">
          {diff === null ? '生成运行对比后查看统计检验。' : '本次对比未提供统计检验结果。'}
        </p>
      )}
    </section>
  )
}
