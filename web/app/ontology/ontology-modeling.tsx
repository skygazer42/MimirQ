'use client'

import { Box } from '@/components/icons'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { OntologyDirectory } from './ontology-directory'
import { OntologyInspector } from './ontology-inspector'
import { OntologyLineage } from './ontology-lineage'
import { OntologyProperties, OntologyRelations } from './ontology-objects'
import { OntologyBindings } from './ontology-bindings'
import { OntologyAssets } from './ontology-assets'
import { OntologyDefinitionEditor } from './ontology-definition-editor'
import type { OntologyController } from './use-ontology-workspace'
import styles from './ontology.module.css'

export function OntologyModeling({ controller: c }: { controller: OntologyController }) {
  return (
    <div className={styles.modeling}>
      <OntologyDirectory controller={c} />
      <div className={styles.modelCanvas}>
        {c.category === 'object_types' ? (
          c.active ? (
            <>
              <div className={styles.objectHeading}>
                <div data-asset="object_types">
                  <span className={styles.iconTray} aria-hidden="true">
                    <Box />
                  </span>
                  <h2>{c.active.label || c.selected}</h2>
                  <span>业务对象</span>
                </div>
                <p>
                  {c.selected} · {Object.keys(c.active.properties).length} 个属性 · {c.active.key.length} 个业务主键
                </p>
              </div>
              <OntologyLineage controller={c} />
              <Tabs value={c.objectTab} onValueChange={c.setObjectTab} className={styles.objectDetails}>
                <TabsList className={styles.detailTabs} aria-label="对象明细">
                  <TabsTrigger value="properties">属性与主键</TabsTrigger>
                  <TabsTrigger value="relations">关联关系</TabsTrigger>
                  <TabsTrigger value="bindings">数据绑定</TabsTrigger>
                  <TabsTrigger value="advanced">高级定义 (JSON)</TabsTrigger>
                </TabsList>
                <TabsContent value="properties">
                  <OntologyProperties controller={c} />
                </TabsContent>
                <TabsContent value="relations">
                  <OntologyRelations controller={c} objectOnly />
                </TabsContent>
                <TabsContent value="bindings">
                  <OntologyBindings controller={c} />
                </TabsContent>
                <TabsContent value="advanced">
                  <OntologyDefinitionEditor controller={c} />
                </TabsContent>
              </Tabs>
            </>
          ) : (
            <section className={styles.inlineEmpty}>
              <Box aria-hidden="true" />
              <h2>从第一个业务对象开始</h2>
              <p>在资产目录中填写新对象标识，再配置属性、主键与关联关系。</p>
              <OntologyDefinitionEditor controller={c} />
            </section>
          )
        ) : (
          <>
            {c.category === 'bindings' ? (
              <>
                <div className={styles.sectionHeading}>
                  <h2>数据绑定</h2>
                  <span>{c.definition.bindings.length} 项绑定</span>
                </div>
                <OntologyBindings controller={c} />
              </>
            ) : c.category === 'relations' ? (
              <>
                <div className={styles.sectionHeading}>
                  <h2>关系</h2>
                  <span>{Object.keys(c.definition.relations).length} 项关系</span>
                </div>
                <OntologyRelations controller={c} />
              </>
            ) : (
              <OntologyAssets controller={c} />
            )}
            <OntologyDefinitionEditor controller={c} />
          </>
        )}
      </div>
      <OntologyInspector controller={c} />
    </div>
  )
}
