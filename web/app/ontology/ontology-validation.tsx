'use client'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { CheckCircle2, ScanLine } from '@/components/icons'
import { BindingPreviewResult } from './ontology-bindings'
import type { OntologyController } from './use-ontology-workspace'
import styles from './ontology.module.css'

export function OntologyValidation({ controller: c }: { controller: OntologyController }) {
  const disabled = Boolean(c.busy) || c.unappliedDefinition
  const canExtract = !disabled && c.objectIds.length > 0 && Boolean(c.documentId.trim() || c.sample.trim())
  return (
    <div className={styles.validation}>
      <aside className={styles.validationControls} aria-label="校验输入">
        <section className={styles.formGroup}>
          <div className={styles.sectionHeading}>
            <h2>数据绑定预检</h2>
            <span>{c.definition.bindings.length} 项绑定</span>
          </div>
          <p className={styles.help}>只读抽样核对身份列、映射与约束。</p>
          <Button
            variant="outline"
            className={styles.startAction}
            disabled={disabled || !c.definition.bindings.length}
            onClick={c.previewBindings}
          >
            <CheckCircle2 aria-hidden="true" />
            预检绑定
          </Button>
        </section>
        <fieldset className={styles.extractionInput} disabled={disabled}>
          <h2 className={styles.sectionTitle}>文档抽取与规则候选</h2>
          <label className={styles.field}>
            文档 ID
            <Input
              value={c.documentId}
              onChange={(event) => c.setDocumentId(event.target.value)}
              placeholder="已解析文档的标识"
            />
          </label>
          <label className={styles.field}>
            或输入抽取样本文本
            <Textarea
              rows={7}
              value={c.sample}
              onChange={(event) => c.setSample(event.target.value)}
              placeholder="粘贴业务制度或样本片段，核对实体、关系和规则条件。"
            />
          </label>
          <p className={styles.help}>填写文档 ID 时优先读取该文档。</p>
          <div className={styles.actions}>
            <Button variant="outline" disabled={!canExtract} onClick={c.previewExtraction}>
              运行抽取预检
            </Button>
            <Button
              variant="outline"
              disabled={!canExtract || !c.definition.bindings.some((item) => item.role === 'primary')}
              onClick={c.previewRules}
            >
              提取规则候选
            </Button>
          </div>
        </fieldset>
      </aside>
      <div className={styles.validationResults} aria-label="预检结果">
        <div className={styles.sectionHeading}>
          <h2>校验结果</h2>
          <span>当前草稿 · {c.definition.ontology || '未命名'}</span>
        </div>
        {!c.bindingResults.length && !c.extraction.length && c.ruleCandidates === null && (
          <div className={styles.inlineEmpty}>
            <ScanLine aria-hidden="true" />
            <h3>尚未运行校验</h3>
            <p>在左侧运行绑定预检或文档抽取。</p>
          </div>
        )}
        {c.bindingResults.map((item) => (
          <BindingPreviewResult item={item} key={item.object_type + ':' + item.role + ':' + item.asset_id} />
        ))}
        {c.extraction.length > 0 && (
          <section className={styles.previewResult} aria-label="文档抽取预检结果">
            <h3 className={styles.sectionTitle}>文档抽取预检</h3>
            {c.extraction.map((item) => (
              <div className={styles.extractionResult} key={item.chunk_id}>
                <p className={styles.help}>
                  分块 {item.chunk_id}
                  {item.page !== null && ' · 第 ' + item.page + ' 页'}
                </p>
                {!item.entities.length && !item.relations.length && !item.rejected.length && (
                  <p className={styles.help}>本分块未抽取到实体或关系。</p>
                )}
                {item.entities.map((entity) => (
                  <figure key={entity.id}>
                    <figcaption>
                      {entity.name} · {entity.object_type}
                    </figcaption>
                    <blockquote>{entity.evidence.quote}</blockquote>
                  </figure>
                ))}
                {item.relations.map((relation, index) => (
                  <figure key={index}>
                    <figcaption>{relation.predicate}</figcaption>
                    <blockquote>{relation.evidence.quote}</blockquote>
                  </figure>
                ))}
                {item.rejected.map((rejected, index) => (
                  <p className={styles.error} key={index}>
                    拒绝项 · {rejected.candidate} · {rejected.reason}
                  </p>
                ))}
              </div>
            ))}
          </section>
        )}
        {c.ruleCandidates !== null && (
          <section className={styles.previewResult} aria-label="规则候选">
            <div className={styles.sectionHeading}>
              <h3>规则候选</h3>
              <span>{c.ruleCandidates.length} 项待审核候选</span>
            </div>
            {!c.ruleCandidates.length && <p className={styles.help}>没有找到可用的规则候选。</p>}
            {c.ruleCandidates.map((candidate) => (
              <article
                className={styles.ruleCandidate}
                key={candidate.chunk_id + ':' + candidate.id + ':' + candidate.evidence.start_char}
              >
                <div className={styles.sectionHeading}>
                  <h4>{candidate.rule.label || candidate.id}</h4>
                  <span className={styles.semanticBadge} data-approval="true">
                    待审核候选
                  </span>
                </div>
                <p className={styles.help}>{candidate.rule.conditions.length} 个条件</p>
                <blockquote>{candidate.evidence.quote}</blockquote>
                <p className={styles.help}>
                  {candidate.rule.object_type} · {candidate.id}
                  {candidate.page !== null && ' · 第 ' + candidate.page + ' 页'}
                </p>
                <details>
                  <summary>查看规则条件</summary>
                  <pre className={styles.jsonPreview}>{JSON.stringify(candidate.rule, null, 2)}</pre>
                </details>
                <Button
                  variant="outline"
                  className={styles.startAction}
                  disabled={disabled || Object.hasOwn(c.definition.rules ?? {}, candidate.id)}
                  onClick={() => c.addRule(candidate)}
                >
                  {Object.hasOwn(c.definition.rules ?? {}, candidate.id) ? '已加入草稿' : '加入草稿'}
                </Button>
              </article>
            ))}
          </section>
        )}
      </div>
    </div>
  )
}
