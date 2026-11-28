'use client'

import { PublishedOntologyWorkspace } from '@/components/enterprise-ontology-published'
import type { OntologyController } from './use-ontology-workspace'
import styles from './ontology.module.css'

export function OntologyRuntime({ controller: c }: { controller: OntologyController }) {
  return (
    <div className={styles.runtime}>
      <div className={styles.runtimeToolbar}>
        <h2>版本运行</h2>
        <label className={styles.versionSelect}>
          发布版本
          <select
            value={c.versionId}
            disabled={Boolean(c.busy) || !c.versions.data?.length}
            onChange={(event) => {
              c.setVersionId(event.target.value)
              c.setIssue('')
            }}
          >
            {!c.versions.data?.length && (
              <option value="">{c.versions.isFetching ? '正在读取发布版本' : '暂无发布版本'}</option>
            )}
            {c.versions.data?.map((item) => (
              <option value={item.id} key={item.id}>
                版本 {item.number} · 草稿修订 {item.draft_revision}
              </option>
            ))}
          </select>
        </label>
        {c.publishedVersion && (
          <span className={styles.fixedVersion} title="运行基于固定发布版本">
            已固定版本
          </span>
        )}
      </div>
      {c.workspace && c.publishedVersion && c.visitedRuntime ? (
        <PublishedOntologyWorkspace
          key={c.publishedVersion.id}
          version={c.publishedVersion}
          versions={c.versions.data!}
          ontologyId={c.workspace.id}
          edoHeaders={c.edoHeaders}
          busy={Boolean(c.busy)}
          run={c.run}
        />
      ) : (
        <div className={styles.inlineEmpty}>
          <h3>{c.workspace ? '尚无可运行的发布版本' : '先选择一个本体草稿'}</h3>
          <p>
            {c.workspace
              ? '发布版本后即可在此问数、问答、生成文书或执行动作。'
              : '选择或新建本体并发布版本后使用。'}
          </p>
        </div>
      )}
    </div>
  )
}
