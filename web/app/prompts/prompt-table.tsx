'use client'

import { Fragment } from 'react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { SearchInput } from '@/components/ui/search-input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { ChevronLeft, ChevronRight, Copy, Edit, Filter, Loader2, MoreHorizontal, Prompts, RefreshCw, Trash2, X } from '@/components/icons'
import type { PromptTemplate } from '@/lib/api/prompts'
import { cn } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { PROMPT_SCENARIOS, promptDate, promptPageNumbers, promptScenario, type ScenarioKey } from './prompt-model'
import type { PromptsController } from './use-prompt-templates'
import styles from './prompts.module.css'

export function PromptStatus({template}:{template:PromptTemplate}) {
  return <span className={cn(styles.status,template.is_active?styles.enabled:styles.disabled)}><i aria-hidden="true"/>{template.is_active?'启用':'停用'}</span>
}
export function PromptVariables({variables,limit=variables.length}:{variables:string[];limit?:number}) {
  if (!variables.length) return <span className={styles.muted}>—</span>
  return <span className={styles.variables}>{variables.slice(0,limit).map(v=><code key={v} className={styles.variable} title={`{${v}}`}>{`{${v}}`}</code>)}{variables.length>limit?<span className={styles.moreVariables} title={variables.slice(limit).map(v=>`{${v}}`).join(', ')}>+{variables.length-limit}</span>:null}</span>
}

function PromptActions({template:t,controller:c}:{template:PromptTemplate;controller:PromptsController}) {
  return <div className={styles.rowActions}>
    <Button variant="ghost" className={styles.previewButton} onClick={()=>c.openPreview(t)} aria-label={`预览 ${t.name}`}>预览</Button>
    {c.canManage?<DropdownMenu>
      <DropdownMenuTrigger asChild><Button variant="ghost" size="icon" className={styles.moreButton} disabled={Boolean(c.busy)} aria-label={`更多操作 ${t.name}`}><MoreHorizontal/></Button></DropdownMenuTrigger>
      <DropdownMenuContent align="end" className={styles.menu} onCloseAutoFocus={event=>{if(c.editorOpen||c.preview||c.deleteTargets.length)event.preventDefault()}}>
        <DropdownMenuItem onSelect={()=>c.openPreview(t)}>阅读模板</DropdownMenuItem>
        <DropdownMenuItem onSelect={()=>{void c.duplicate(t)}}><Copy/>复制为自定义模板</DropdownMenuItem>
        {!t.is_system?<>
          <DropdownMenuItem onSelect={()=>c.openEditor(t)}><Edit/>编辑模板</DropdownMenuItem>
          <DropdownMenuItem onSelect={()=>{void c.toggleActive(t)}}>{t.is_active?'停用模板':'启用模板'}</DropdownMenuItem>
          <DropdownMenuSeparator/>
          <DropdownMenuItem className={styles.dangerText} onSelect={()=>c.openDelete([t])}><Trash2/>删除模板</DropdownMenuItem>
        </>:null}
      </DropdownMenuContent>
    </DropdownMenu>:null}
  </div>
}

export function PromptTable({controller:c}:{controller:PromptsController}) {
  const hasFilters=c.filters.query.trim()||c.filters.scenario!=='all'||c.filters.status!=='all'||c.filters.source!=='all'||c.filters.category!=='all'
  const quietEmpty=c.query.isSuccess&&c.templates.length===0&&!hasFilters
  const pageNumbers=promptPageNumbers(c.currentPage,c.totalPages)
  const activeCount=c.templates.filter(t=>t.is_active).length
  return <>
    <Tabs value={c.filters.scenario} onValueChange={value=>c.changeFilter('scenario',value as ScenarioKey)} className={styles.scenarios}>
      <TabsList aria-label="提示词场景" className={styles.tabs}>
        {PROMPT_SCENARIOS.filter(s=>s.key!=='other'||c.counts.other>0).map(s=><TabsTrigger key={s.key} value={s.key} className={styles.tab}>{s.label}{quietEmpty?null:<span>{c.counts[s.key]??0}</span>}</TabsTrigger>)}
      </TabsList>
    </Tabs>
    <div className={styles.toolbar}>
      <SearchInput aria-label="搜索模板" value={c.filters.query} onValueChange={value=>c.changeFilter('query',value)} placeholder="搜索名称、内容或标签" containerClassName={styles.search} inputClassName={styles.searchInput}/>
      <div className={styles.filters}>
        <Select value={c.filters.status} onValueChange={value=>c.changeFilter('status',value as typeof c.filters.status)}>
          <SelectTrigger aria-label="模板状态" className={styles.filterSelect}><SelectValue/></SelectTrigger>
          <SelectContent><SelectItem value="all">全部状态</SelectItem><SelectItem value="active">已启用</SelectItem><SelectItem value="inactive">已停用</SelectItem></SelectContent>
        </Select>
        <Select value={c.filters.source} onValueChange={value=>c.changeFilter('source',value as typeof c.filters.source)}>
          <SelectTrigger aria-label="模板来源" className={styles.filterSelect}><SelectValue/></SelectTrigger>
          <SelectContent><SelectItem value="all">全部来源</SelectItem><SelectItem value="system">内置模板</SelectItem><SelectItem value="custom">自定义模板</SelectItem></SelectContent>
        </Select>
        <Popover>
          <PopoverTrigger asChild><Button variant="ghost" size="icon" aria-label="更多筛选与排序" className={cn(styles.filterButton,c.filters.category!=='all'&&styles.filterActive)}><Filter/></Button></PopoverTrigger>
          <PopoverContent align="start" className={styles.filterPopover}>
            <div><Label htmlFor="prompt-category-filter">分类</Label><Select value={c.filters.category} onValueChange={value=>c.changeFilter('category',value)}><SelectTrigger id="prompt-category-filter" aria-label="模板分类"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="all">全部分类</SelectItem>{c.categories.map(category=><SelectItem key={category} value={category}>{category}</SelectItem>)}</SelectContent></Select></div>
            <div><Label htmlFor="prompt-order">排序</Label><Select value={c.filters.sort} onValueChange={value=>c.changeFilter('sort',value as typeof c.filters.sort)}><SelectTrigger id="prompt-order" aria-label="模板排序"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="updated">最近更新</SelectItem><SelectItem value="name">名称 A–Z</SelectItem><SelectItem value="usage">使用次数最多</SelectItem></SelectContent></Select></div>
            {hasFilters?<Button variant="ghost" onClick={c.clearFilters}>清除筛选</Button>:null}
          </PopoverContent>
        </Popover>
        {c.filters.category!=='all'?<Button variant="ghost" className={styles.categoryChip} onClick={()=>c.changeFilter('category','all')} title="清除分类筛选">{c.filters.category}<X/></Button>:null}
      </div>
      {quietEmpty?null:<span className={styles.collectionCount} role="status">{c.query.isLoading?'加载中':c.query.isFetching?'正在更新':`共 ${c.filtered.length} 个模板`}</span>}
    </div>
    {c.selectedCount>0?<div className={styles.selectionBar} role="region" aria-label="批量操作">
      <span>已选择 {c.selectedCount} 个模板</span>
      {c.selectedCount>c.selectedPageCount?<small>含其他页的选择</small>:null}
      <div><Button variant="ghost" disabled={Boolean(c.busy)} onClick={()=>{void c.batchActive(true)}}>批量启用</Button><Button variant="ghost" disabled={Boolean(c.busy)} onClick={()=>{void c.batchActive(false)}}>批量停用</Button><Button variant="ghost" className={styles.dangerText} disabled={Boolean(c.busy)} onClick={()=>c.openDelete(c.selectedTemplates)}>批量删除</Button><Button variant="ghost" size="icon" disabled={Boolean(c.busy)} aria-label="取消选择" onClick={c.clearSelection}><X/></Button></div>
    </div>:null}
    {c.actionError&&!c.editorOpen&&!c.deleteTargets.length?<div className={styles.errorBar} role="alert"><span>{c.actionError}</span><Button variant="ghost" size="icon" aria-label="关闭操作错误" onClick={()=>c.setActionError('')}><X/></Button></div>:null}
    {c.query.isError&&c.templates.length>0?<div className={styles.errorBar} role="alert"><span>列表更新失败：{formatApiError(c.query.error,'请重试')}</span><Button variant="ghost" disabled={c.query.isFetching} onClick={()=>{void c.query.refetch()}}>重试</Button></div>:null}
    <div className={styles.tableScroll} aria-busy={c.query.isFetching}>
      {quietEmpty?null:<table className={styles.table} aria-label="提示词模板">
        <colgroup><col className={styles.checkColumn}/><col className={styles.nameColumn}/><col className={styles.sceneColumn}/><col className={styles.sourceColumn}/><col className={styles.variablesColumn}/><col className={styles.usageColumn}/><col className={styles.dateColumn}/><col className={styles.statusColumn}/><col className={styles.actionsColumn}/></colgroup>
        <thead><tr>
          <th className={styles.checkColumn}><Checkbox aria-label="选择本页自定义模板" title="仅选择本页可编辑的自定义模板" disabled={!c.canManage||!c.selectablePage.length||Boolean(c.busy)} checked={c.selectedPageCount===0?false:c.selectedPageCount===c.selectablePage.length?true:'indeterminate'} onCheckedChange={c.togglePage}/></th>
          <th className={styles.nameColumn} scope="col">模板名称</th><th className={styles.sceneColumn} scope="col">场景</th><th className={styles.sourceColumn} scope="col">来源</th><th className={styles.variablesColumn} scope="col">变量</th><th className={styles.usageColumn} scope="col">使用次数</th><th className={styles.dateColumn} scope="col">更新时间</th><th className={styles.statusColumn} scope="col">状态</th><th className={styles.actionsColumn} scope="col">操作</th>
        </tr></thead>
        <tbody>
          {c.query.isLoading?Array.from({length:8},(_,i)=><tr key={i} aria-hidden="true"><td colSpan={9} className={styles.skeletonCell}><div className={styles.skeleton}/></td></tr>):c.pageItems.map(t=>{
            const scene=promptScenario(t.category)
            return <tr key={t.id} data-selected={c.selectedIds.has(t.id)||undefined}>
              <td className={styles.checkColumn}><Checkbox checked={c.selectedIds.has(t.id)} disabled={!c.canManage||t.is_system||Boolean(c.busy)} title={t.is_system?'内置模板只读，复制后可修改':undefined} aria-label={`选择 ${t.name}`} onCheckedChange={()=>c.toggleOne(t)}/></td>
              <td className={styles.nameColumn}><div className={styles.templateIdentity}><span className={cn(styles.objectIcon,styles[scene.tone])}><Prompts/></span><div><button className={styles.nameButton} data-prompt-open={t.id} onClick={()=>c.openPreview(t)} title={t.name}>{t.name}</button><p className={styles.templateDescription} title={t.description??undefined}>{t.description||'暂无描述'}</p><span className={styles.mobileMeta}>{scene.label} · {t.is_system?'内置':'自定义'}</span></div></div></td>
              <td className={styles.sceneColumn}><span className={cn(styles.sceneLabel,styles[scene.tone])}><i aria-hidden="true"/>{scene.label}</span></td>
              <td className={styles.sourceColumn}><span className={t.is_system?styles.muted:styles.customSource}>{t.is_system?'内置':'自定义'}</span></td>
              <td className={styles.variablesColumn}><PromptVariables variables={t.variables} limit={2}/></td>
              <td className={styles.usageColumn}>{t.usage_count.toLocaleString()}</td><td className={styles.dateColumn}><time dateTime={t.updated_at} title={promptDate(t.updated_at,true)}>{promptDate(t.updated_at)}</time></td>
              <td className={styles.statusColumn}><PromptStatus template={t}/></td><td className={styles.actionsColumn}><PromptActions template={t} controller={c}/></td>
            </tr>
          })}
        </tbody>
      </table>}
      {!c.query.isLoading&&!c.pageItems.length?<section className={styles.empty}>
        {c.query.isError?<><h2>提示词加载失败</h2><p role="alert">{formatApiError(c.query.error,'请重试')}</p><Button variant="outline" disabled={c.query.isFetching} onClick={()=>{void c.query.refetch()}}><RefreshCw/>重新加载</Button></>:hasFilters?<><h2>没有匹配的模板</h2><p>调整搜索或筛选条件后再试。</p><Button variant="outline" onClick={c.clearFilters}>清除筛选</Button></>:<><Prompts appearance="color" className={styles.emptyIcon}/><h2>还没有提示词模板</h2><p>{c.canManage?'创建自定义模板，或同步项目内置模板。':'管理员添加模板后，会显示在这里。'}</p>{c.canManage?<Button variant="outline" disabled={Boolean(c.busy)} onClick={()=>{void c.syncBuiltins()}}>{c.busy==='sync'?<Loader2 className="animate-spin"/>:<RefreshCw/>}{c.busy==='sync'?'同步中':'同步内置模板'}</Button>:null}</>}
      </section>:null}
    </div>
    {quietEmpty?null:<footer className={styles.footer}>
      <span className={styles.resultCount}>{hasFilters?`找到 ${c.filtered.length} 个 / 全部 ${c.templates.length} 个`:`共 ${c.templates.length} 个模板 · ${activeCount} 个启用`}</span>
      <div className={styles.pagination}>
        <Select value={String(c.pageSize)} onValueChange={value=>c.changePageSize(Number(value))}><SelectTrigger aria-label="每页模板数" className={styles.pageSize}><SelectValue/></SelectTrigger><SelectContent>{[20,50,100].map(size=><SelectItem key={size} value={String(size)}>{size} 条 / 页</SelectItem>)}</SelectContent></Select>
        <Button variant="ghost" size="icon" aria-label="上一页" disabled={c.currentPage<=1} onClick={()=>c.setPage(c.currentPage-1)}><ChevronLeft/></Button>
        <div className={styles.pageNumbers}>{pageNumbers.map((page,i)=><Fragment key={page}>{i>0&&page-pageNumbers[i-1]>1?<span>…</span>:null}<Button variant="ghost" aria-label={`第 ${page} 页`} aria-current={c.currentPage===page?'page':undefined} className={c.currentPage===page?styles.currentPage:undefined} onClick={()=>c.setPage(page)}>{page}</Button></Fragment>)}</div>
        <span className={styles.mobilePage}>第 {c.currentPage} / {c.totalPages} 页</span><Button variant="ghost" size="icon" aria-label="下一页" disabled={c.currentPage>=c.totalPages} onClick={()=>c.setPage(c.currentPage+1)}><ChevronRight/></Button>
      </div>
    </footer>}
  </>
}
