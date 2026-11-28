'use client'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import type { OntologyController } from './use-ontology-workspace'
import styles from './ontology.module.css'

export function OntologyAssetScope({ controller: c }: { controller: OntologyController }) {
  return (
    <div className={styles.formGroup}>
      <label className={styles.field}>
        资产知识库
        <select
          value={c.assetDatasetId}
          onChange={(event) => {
            c.setAssetDatasetId(event.target.value)
            c.setSuggestionAssets([])
            c.setSuggestion(null)
          }}
        >
          <option value="">{c.datasets.isPending ? '正在读取知识库' : '选择资产所在的知识库'}</option>
          {c.datasets.data?.map((dataset) => (
            <option value={dataset.id} key={dataset.id}>
              {dataset.name}
            </option>
          ))}
        </select>
      </label>
      {c.assetDatasetId && c.assets.isFetching && <p className={styles.help}>正在读取登记资产</p>}
      {c.assetDatasetId && c.assets.isSuccess && !c.assets.data.length && (
        <p className={styles.help}>该知识库没有可选资产</p>
      )}
      {c.datasets.isError && (
        <p role="alert" className={styles.error}>
          {c.datasets.error.message}
        </p>
      )}
      {c.assets.isError && (
        <p role="alert" className={styles.error}>
          {c.assets.error.message}
        </p>
      )}
    </div>
  )
}

export function OntologyImport({ controller: c }: { controller: OntologyController }) {
  return (
    <Dialog
      open={c.importOpen}
      onOpenChange={(open) => {
        if (!c.busy) c.setImportOpen(open)
      }}
    >
      <DialogContent className={styles.importDialog}>
        <DialogHeader>
          <DialogTitle>导入与生成</DialogTitle>
          <DialogDescription>导入 YAML/JSON 定义，或基于资产与样本生成本体草案。</DialogDescription>
        </DialogHeader>
        <div className={styles.importBody}>
          {c.issue && (
            <p role="alert" className={styles.error}>
              {c.issue}
            </p>
          )}
          {c.busy && (
            <p role="status" className={styles.help}>
              {c.busy}
            </p>
          )}
          <fieldset disabled={Boolean(c.busy) || c.unappliedDefinition} className={styles.formGroup}>
            <h3 className={styles.sectionTitle}>导入 YAML 或 JSON</h3>
            <Textarea
              aria-label="本体定义文件内容"
              rows={5}
              className={styles.code}
              value={c.importText}
              onChange={(event) => c.setImportText(event.target.value)}
            />
            <Button
              variant="outline"
              className={styles.startAction}
              disabled={!c.importText.trim()}
              onClick={() =>
                void c.run('校验定义', async () => {
                  await c.applyDefinition(c.importText)
                  c.setImportOpen(false)
                })
              }
            >
              导入到编辑区
            </Button>
          </fieldset>
          <fieldset disabled={Boolean(c.busy) || c.unappliedDefinition} className={styles.suggestion}>
            <h3 className={styles.sectionTitle}>从资产与样本生成</h3>
            <OntologyAssetScope controller={c} />
            {Boolean(c.assets.data?.length) && (
              <label className={styles.field}>
                添加参考资产
                <select
                  value=""
                  disabled={c.suggestionAssets.length >= 8}
                  onChange={(event) => {
                    c.setSuggestionAssets([...c.suggestionAssets, event.target.value])
                    c.setSuggestion(null)
                  }}
                >
                  <option value="">{c.suggestionAssets.length >= 8 ? '最多选择 8 个资产' : '选择参考资产'}</option>
                  {c.assets.data
                    ?.filter((item) => !c.suggestionAssets.includes(item.id))
                    .map((asset) => (
                      <option value={asset.id} key={asset.id}>
                        {asset.label}
                      </option>
                    ))}
                </select>
              </label>
            )}
            {c.suggestionAssets.length > 0 && (
              <ul className={styles.chips}>
                {c.suggestionAssets.map((id) => (
                  <li key={id}>
                    {c.assets.data?.find((item) => item.id === id)?.label ?? id}
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={'移除参考资产 ' + id}
                      onClick={() => {
                        c.setSuggestionAssets(c.suggestionAssets.filter((item) => item !== id))
                        c.setSuggestion(null)
                      }}
                    >
                      移除
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <label className={styles.field}>
              参考文档摘录
              <Textarea
                rows={3}
                maxLength={12000}
                value={c.suggestionSample}
                onChange={(event) => {
                  c.setSuggestionSample(event.target.value)
                  c.setSuggestion(null)
                }}
              />
            </label>
            <Button
              variant="outline"
              className={styles.startAction}
              disabled={
                !c.definition.ontology.trim() ||
                !c.assetDatasetId ||
                (!c.suggestionAssets.length && !c.suggestionSample.trim())
              }
              onClick={c.generateSuggestion}
            >
              生成草案
            </Button>
            {c.suggestion && (
              <div className={styles.formGroup}>
                {c.suggestion.sources.length > 0 && (
                  <ul className={styles.help}>
                    {c.suggestion.sources.map((source) => (
                      <li key={source.id}>
                        {source.label}
                        {source.columns.length > 0 && ' · ' + source.columns.join('、')}
                      </li>
                    ))}
                  </ul>
                )}
                <details>
                  <summary>查看草案定义</summary>
                  <pre className={styles.jsonPreview}>{JSON.stringify(c.suggestion.definition, null, 2)}</pre>
                </details>
                <p className={styles.help}>应用将替换当前草稿。</p>
                <Button
                  variant="outline"
                  className={styles.startAction}
                  onClick={() => {
                    c.loadDefinition(c.suggestion!.definition)
                    c.setImportOpen(false)
                  }}
                >
                  应用到编辑区
                </Button>
              </div>
            )}
          </fieldset>
        </div>
      </DialogContent>
    </Dialog>
  )
}
