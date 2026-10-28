import { PARSER_BACKEND_REGISTRY_OPTIONS } from '@/lib/parser-options'
import type { IngestionPolicy } from '@/types'
import styles from './precheck.module.css'

export function PolicySuggestionSummary({ policy }: { policy: IngestionPolicy }) {
  const rules = policy.rules ?? []
  return <section aria-labelledby="precheck-suggested-rules"><h3 id="precheck-suggested-rules" className="text-sm font-semibold">建议规则 · {rules.length} 条</h3><p className="mt-1 text-sm leading-6 text-muted-foreground">应用后用于后续入库，不会重新处理已有文档。</p>
    {rules.length ? <ol className={styles.policyRules}>{rules.map((rule, index) => <li key={rule.id} className={styles.policyRule}><div><h4><span className="mr-2 tabular-nums text-muted-foreground">{index + 1}.</span>{rule.name}{!rule.enabled ? <span className="ml-2 text-xs text-muted-foreground">未启用</span> : null}</h4><p>{rule.match?.extensions?.length ? rule.match.extensions.join(' · ') : '任意文件类型'}</p>{rule.match?.filename_regex ? <p className={styles.rulePattern}>文件名匹配：<code>{rule.match.filename_regex}</code></p> : null}</div><div className={styles.ruleMethod}><span>{PARSER_BACKEND_REGISTRY_OPTIONS.find(item => item.value === rule.parser_backend)?.label ?? rule.parser_backend ?? '默认解析器'}</span><small>{rule.chunk_strategy || '默认切块策略'}</small></div></li>)}</ol> : <p className="mt-3 text-sm text-warning">本次建议不含规则；覆盖应用会清空已有策略。</p>}
  </section>
}
