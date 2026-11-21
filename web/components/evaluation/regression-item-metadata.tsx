import {
  formatRegressionCount,
  formatRegressionMetric,
  regressionItemMetadataSchema,
} from '@/lib/regression-result-model'

export function RegressionItemMetadata({ metadata }: Readonly<{ metadata: Readonly<Record<string, unknown>> }>) {
  const parsed = regressionItemMetadataSchema.safeParse(metadata)
  if (!parsed.success) {
    return (
      <p role="alert" className="mt-2 text-sm text-destructive">
        当前样本的附加信息格式不正确，原始结果已保留。
      </p>
    )
  }
  const meta = parsed.data
  const metadataHit = meta.expected_metadata_hit
  const missingFields = meta.expected_metadata_missing_keys
  const explanations = meta.explanations && Object.entries(meta.explanations)
  const judge = meta.llm_judge
  const hasExpectedMetadata = [
    metadataHit,
    meta.expected_metadata_recall,
    meta.expected_metadata_fields_matched,
    meta.expected_metadata_fields_total,
    missingFields,
  ].some((value) => value != null)
  return (
    <>
      {hasExpectedMetadata ? (
        <details className="mt-2 rounded-md border border-success/30 bg-success/5 p-2">
          <summary className="cursor-pointer select-none text-[13px] font-medium text-success">
            业务元数据
            {metadataHit == null ? null : ` · ${metadataHit ? '命中' : '未命中'}`}
          </summary>
          <div className="mt-2 flex flex-wrap gap-2 text-[13px] text-muted-foreground">
            <span className="rounded-full border border-success/30 bg-card px-2 py-0.5">
              expected_metadata_recall: {formatRegressionMetric(meta.expected_metadata_recall)}
            </span>
            <span className="rounded-full border border-success/30 bg-card px-2 py-0.5">
              expected_metadata_fields_matched: {formatRegressionCount(meta.expected_metadata_fields_matched)}/
              {formatRegressionCount(meta.expected_metadata_fields_total)}
            </span>
          </div>
          {missingFields && missingFields.length > 0 ? (
            <div className="mt-2 text-[13px] leading-5 text-muted-foreground">
              <span className="font-medium text-foreground/80">已返回的缺失字段:</span> {missingFields.join(', ')}
            </div>
          ) : null}
        </details>
      ) : null}
      {explanations && explanations.length > 0 ? (
        <details className="mt-2">
          <summary className="text-[13px] text-muted-foreground cursor-pointer select-none">解释</summary>
          <div className="mt-2 space-y-1 text-[13px] text-muted-foreground">
            {explanations.map(([key, text]) => (
              <div key={key} className="flex gap-2">
                <span className="font-medium text-foreground/80">{key}:</span>
                <span className="break-words">{text}</span>
              </div>
            ))}
          </div>
        </details>
      ) : null}
      {judge?.enabled ? (
        <details className="mt-2">
          <summary className="text-[13px] text-muted-foreground cursor-pointer select-none">
            LLM Judge · overall={formatRegressionMetric(judge.overall_score)}
          </summary>
          <div className="mt-2 space-y-2 text-[13px] text-muted-foreground">
            {judge.model_used != null ? (
              <div className="font-mono text-[13px] text-muted-foreground">model: {judge.model_used}</div>
            ) : null}
            {[
              { key: 'retrieval', part: judge.retrieval },
              { key: 'generation', part: judge.generation },
            ].map(({ key, part }) =>
              part == null ? null : (
                <div key={key} className="rounded-md border border-border/60 bg-muted/30 p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-foreground/80">{key}</span>
                    <span className="tabular-nums">{formatRegressionMetric(part.score)}</span>
                  </div>
                  {part.reason != null ? <div className="mt-1 text-muted-foreground">{part.reason}</div> : null}
                  {part.evidence_quotes && part.evidence_quotes.length > 0 ? (
                    <div className="mt-2 space-y-1">
                      {part.evidence_quotes.map((quote, index) => (
                        <div key={`${index}:${quote}`} className="font-mono text-[13px] text-muted-foreground">
                          “{quote}”
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ),
            )}
          </div>
        </details>
      ) : null}
    </>
  )
}
