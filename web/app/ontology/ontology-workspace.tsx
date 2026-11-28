'use client'

import { Box, Network, Plus, Upload, Save, Loader2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { SplitEmptyStudio } from '@/components/ui/split-empty-studio'
import { useOntologyWorkspace } from './use-ontology-workspace'
import { ontologyErrorText } from './ontology-model'
import { OntologyModeling } from './ontology-modeling'
import { OntologyValidation } from './ontology-validation'
import { OntologyRuntime } from './ontology-runtime'
import { OntologyImport } from './ontology-import'
import styles from './ontology.module.css'

export function OntologyWorkspace({ sessionKey }: { sessionKey: string }) {
  const c = useOntologyWorkspace(sessionKey)
  const loading = c.workspaces.isPending || (c.workspaces.isSuccess && c.workspaces.data.length > 0 && !c.started)
  const empty = c.workspaces.isSuccess && c.workspaces.data.length === 0 && !c.started
  const saveDisabled = Boolean(c.busy) || c.unappliedDefinition || !c.definition.ontology.trim() || !c.objectIds.length
  const publishDisabled = Boolean(c.busy) || c.unappliedDefinition || !c.workspace || c.dirty || c.versions.isFetching
  const published =
    !c.dirty &&
    !c.unappliedDefinition &&
    c.workspace &&
    c.publishedVersion?.draft_revision === c.workspace.draft_revision
  function openImport() {
    if (!c.started) c.openWorkspace('')
    c.setImportOpen(true)
  }
  function draftCode() {
    return (
      <label className={styles.draftCode}>
        <span className="sr-only">本体标识</span>
        <Input
          aria-label="本体标识"
          placeholder="本体标识"
          value={c.definition.ontology}
          disabled={!c.started || Boolean(c.workspace) || Boolean(c.busy) || c.unappliedDefinition}
          onChange={(event) => c.mutate({ ...c.definition, ontology: event.target.value })}
        />
      </label>
    )
  }
  function saveButton() {
    return (
      <Button variant="outline" aria-label="保存草稿" disabled={saveDisabled} onClick={() => void c.save()}>
        <Save aria-hidden="true" />
        保存草稿{c.dirty && <span className={styles.unsavedDot} aria-label="有未保存更改" />}
      </Button>
    )
  }
  function publishButton() {
    return (
      <Button className={styles.primary} disabled={publishDisabled} onClick={() => void c.publish()}>
        <Upload aria-hidden="true" />
        发布版本
      </Button>
    )
  }
  return (
    <section
      className={styles.workspace}
      aria-label="企业本体工作台"
      aria-busy={Boolean(c.busy)}
      data-ontology-workbench
    >
      <Tabs value={c.stage} onValueChange={c.changeStage} className={styles.lifecycleRoot}>
        <header className={styles.header} data-ontology-header>
          <div className={styles.heading}>
            <PageTitleIcon name="ontology" />
            <h1>企业本体</h1>
          </div>
          <select
            aria-label="本体草稿"
            className={styles.draftSelect}
            value={c.workspace?.id ?? ''}
            disabled={loading || c.workspaces.isError || Boolean(c.busy)}
            onChange={(event) => c.openWorkspace(event.target.value)}
          >
            <option value="">{loading ? '读取本体…' : empty ? '选择或新建本体' : '新建本体'}</option>
            {c.workspaces.data?.map((item) => (
              <option value={item.id} key={item.id}>
                {item.code}
              </option>
            ))}
          </select>
          {!c.workspace && <div className={styles.desktopCode}>{draftCode()}</div>}
          <span className={styles.draftStatus} data-published={Boolean(published)}>
            {c.dirty || c.unappliedDefinition
              ? '未保存'
              : c.workspace
                ? c.publishedVersion?.draft_revision === c.workspace.draft_revision
                  ? '已发布 v' + c.publishedVersion.number
                  : '草稿 · 修订 ' + c.workspace.draft_revision
                : '新草稿'}
          </span>
          <TabsList className={styles.lifecycleTabs} aria-label="本体生命周期">
            <TabsTrigger value="model">建模</TabsTrigger>
            <TabsTrigger value="validation">校验</TabsTrigger>
            <TabsTrigger value="runtime">运行应用</TabsTrigger>
          </TabsList>
          <div className={styles.headerActions}>
            <Button
              variant="ghost"
              aria-label="导入与生成"
              disabled={loading || c.workspaces.isError || Boolean(c.busy)}
              onClick={openImport}
            >
              <Plus aria-hidden="true" />
              <span>导入与生成</span>
            </Button>
            <div className={styles.desktopActions}>
              {saveButton()}
              {publishButton()}
            </div>
          </div>
        </header>
        {!empty && !loading && !c.workspaces.isError && (
          <div className={styles.phoneActions}>
            {!c.workspace && draftCode()}
            {saveButton()}
            {publishButton()}
          </div>
        )}
        {(c.issue || c.busy || c.notice || c.unappliedDefinition || c.hasEdo || c.versions.isError) && (
          <div className={styles.feedback}>
            {c.issue && (
              <p role="alert" className={styles.error}>
                {c.issue}
              </p>
            )}
            {(c.busy || c.notice) && <p role="status">{c.busy || c.notice}</p>}
            {c.unappliedDefinition && (
              <p className={styles.help}>高级定义有未应用的修改。校验并应用后才能保存或发布。</p>
            )}
            {c.versions.isError && (
              <div className={styles.actions}>
                <p role="alert" className={styles.error}>
                  发布版本读取失败 · {ontologyErrorText(c.versions.error)}
                </p>
                <Button variant="outline" onClick={() => void c.versions.refetch()}>
                  重试读取版本
                </Button>
              </div>
            )}
            {c.hasEdo && (
              <label className={styles.edoCredential}>
                EDO 登录凭证
                <Input
                  type="password"
                  autoComplete="off"
                  value={c.edoCredential}
                  onChange={(event) => c.setEdoCredential(event.target.value)}
                />
              </label>
            )}
          </div>
        )}
        {loading ? (
          <div className={styles.loading} role="status">
            <Loader2 className="animate-spin" aria-hidden="true" />
            正在读取企业本体…
          </div>
        ) : c.workspaces.isError ? (
          <div className={styles.loadError}>
            <Network aria-hidden="true" />
            <h2>企业本体加载失败</h2>
            <p role="alert">{ontologyErrorText(c.workspaces.error)}</p>
            <Button variant="outline" onClick={() => void c.workspaces.refetch()}>
              重新加载
            </Button>
          </div>
        ) : empty ? (
          <SplitEmptyStudio
            className={styles.empty}
            illustration={<Network />}
            title="还没有企业本体"
            description="统一管理业务对象、数据映射与可执行规则。"
            actions={
              <>
                <Button className={styles.primary} onClick={() => c.openWorkspace('')}>
                  <Plus />
                  新建本体
                </Button>
                <Button variant="outline" onClick={openImport}>
                  导入或从资产生成
                </Button>
              </>
            }
            stepsHeading="从业务定义到实际应用"
            steps={[
              { index: '01', title: '定义对象与关系', description: '明确业务身份、属性和对象之间的关联。' },
              {
                index: '02',
                title: '绑定数据资产与行为规则',
                description: '映射真实来源，核对指标口径、规则和业务动作。',
              },
              {
                index: '03',
                title: '发布版本并用于问数、问答与执行',
                description: '固定业务定义，连接知识库证据并保留执行回执。',
              },
            ]}
          />
        ) : (
          <div className={styles.stageContent}>
            <TabsContent value="model" className={styles.stagePanel}>
              <OntologyModeling controller={c} />
            </TabsContent>
            <TabsContent value="validation" className={styles.stagePanel}>
              <OntologyValidation controller={c} />
            </TabsContent>
            <TabsContent value="runtime" forceMount className={styles.stagePanel + ' data-[state=inactive]:hidden'}>
              <OntologyRuntime controller={c} />
            </TabsContent>
          </div>
        )}
      </Tabs>
      <OntologyImport controller={c} />
      <span className="sr-only">
        <Box aria-hidden="true" />
        十一类企业本体资产
      </span>
    </section>
  )
}
