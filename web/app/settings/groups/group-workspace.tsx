'use client'

import {AppFrame} from '@/components/app-frame'
import {Button} from '@/components/ui/button'
import {PageTitleIcon} from '@/components/ui/page-title-icon'
import {SearchInput} from '@/components/ui/search-input'
import {Select,SelectContent,SelectItem,SelectTrigger,SelectValue} from '@/components/ui/select'
import {DropdownMenu,DropdownMenuContent,DropdownMenuItem,DropdownMenuSeparator,DropdownMenuTrigger} from '@/components/ui/dropdown-menu'
import {ArrowLeft,ChevronLeft,ChevronRight,Copy,Loader2,MoreHorizontal,Pencil,Plus,RefreshCw,Trash2,UserPlus,Users} from '@/components/icons'
import {formatApiError} from '@/lib/api-errors'
import {cn} from '@/lib/utils'
import {formatGroupDate,memberIdentity} from './groups-model'
import {useGroupDirectory,type GroupDirectoryController} from './use-group-directory'
import {GroupDialogs} from './group-dialogs'
import styles from './groups.module.css'

function Notice({error,label,retry}:{error:unknown;label:string;retry:()=>unknown}) {return <div role="alert" className={styles.domainError}><span>{formatApiError(error,label)}</span><Button variant="ghost" onClick={()=>{void retry()}}>重试</Button></div>}
function GroupDirectory({controller:c}:{controller:GroupDirectoryController}) {
  return <aside className={styles.directory} aria-label="组目录">
    <div className={styles.directoryHead}><div className={styles.directoryTitle}><h2>组目录</h2><span>当前租户</span></div>
      <SearchInput aria-label="搜索组" value={c.scope.query} onValueChange={query=>c.updateScope({query,page:1})} placeholder="搜索组名称或标识" inputClassName={styles.directorySearch}/>
      <Select value={c.scope.external} onValueChange={external=>c.updateScope({external:external as 'all'|'filled'|'empty',page:1})}><SelectTrigger aria-label="筛选外部组 ID" className={styles.externalFilter}><SelectValue/></SelectTrigger><SelectContent><SelectItem value="all">全部外部标识</SelectItem><SelectItem value="filled">已填写外部 ID</SelectItem><SelectItem value="empty">未填写外部 ID</SelectItem></SelectContent></Select>
    </div>
    <div className={styles.directoryList}>
      {c.directoryQuery.isError?<Notice error={c.directoryQuery.error} label="组目录获取失败" retry={c.directoryQuery.refetch}/>:null}
      {c.directoryQuery.isPending?<p className={styles.directoryState} role="status">正在读取组目录…</p>:c.directoryPage.items.length?<nav aria-label="选择组">{c.directoryPage.items.map(group=><button key={group.id} className={cn(styles.directoryRow,c.selectedId===group.id&&styles.selected)} aria-label={`打开组 ${group.name}`} aria-current={c.selectedId===group.id?'true':undefined} disabled={Boolean(c.busy)} onClick={()=>c.selectGroup(group.id)}><Users/><span><strong>{group.name}</strong><small>{group.external_id||'未填写外部 ID'}</small></span><ChevronRight/></button>)}</nav>:!c.directoryQuery.isError?<div className={styles.directoryState}><p>{c.scope.query||c.scope.external!=='all'?'没有匹配的组。':'还没有组。'}</p>{c.scope.query||c.scope.external!=='all'?<Button variant="ghost" onClick={()=>c.updateScope({query:'',external:'all',page:1})}>清除筛选</Button>:null}</div>:null}
    </div>
  </aside>
}

function GroupDetails({controller:c}:{controller:GroupDirectoryController}) {
  const group=c.group
  const missing=(c.groupQuery.error as {response?:{status?:number}}|null)?.response?.status===404
  if(!c.selectedId)return <section className={styles.emptyDetail} aria-label="组详情"><Users/><h2>{c.directoryQuery.isError?'组目录暂不可用':c.directoryQuery.isPending?'正在读取组目录…':'还没有组'}</h2>{!c.directoryQuery.isError&&!c.directoryQuery.isPending?<p>新建组后，可以把需要协作的成员添加进来。</p>:null}</section>
  if(missing||(!group&&c.groupQuery.isError))return <section className={styles.emptyDetail} aria-label="组详情"><Users/><h2>{missing?'该组已不存在或不可访问':'组信息获取失败'}</h2><p>{formatApiError(c.groupQuery.error,'无法读取当前组。')}</p><div><Button variant="outline" onClick={()=>{void c.groupQuery.refetch()}}>重试</Button><Button variant="ghost" onClick={()=>c.updateScope({groupId:'',view:'directory'})}>返回组目录</Button></div></section>
  if(!group)return <section className={styles.emptyDetail} role="status">正在读取组信息…</section>
  return <section className={styles.details} aria-label={`组详情 ${group.name}`}>
    <Button variant="ghost" className={styles.returnToDirectory} onClick={()=>c.updateScope({view:'directory'})}><ArrowLeft/>返回组目录</Button>
    <header className={styles.detailHeading}><Users/><h2>{group.name}</h2><span className={styles.spacer}/>{c.canManage?<>
      <Button variant="outline" aria-label="编辑组信息" disabled={Boolean(c.busy)} data-groups-edit onClick={event=>c.openEditor('edit',event.currentTarget)}><Pencil/><span>编辑组信息</span></Button>
      <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" disabled={Boolean(c.busy)} aria-label={`组操作 ${group.name}`}><MoreHorizontal/></Button></DropdownMenuTrigger><DropdownMenuContent align="end" onCloseAutoFocus={event=>{if(c.deletion)event.preventDefault()}}><DropdownMenuItem onSelect={()=>{void c.copyId(group.id)}}><Copy/>复制组 ID</DropdownMenuItem><DropdownMenuSeparator/><DropdownMenuItem className="text-destructive" onSelect={()=>{const element=document.querySelector<HTMLElement>('[data-groups-edit]');if(element)c.openDeletion(element)}}><Trash2/>删除组</DropdownMenuItem></DropdownMenuContent></DropdownMenu>
    </>:<Button variant="ghost" aria-label="复制组 ID" onClick={()=>{void c.copyId(group.id)}}><Copy/></Button>}</header>
    {c.groupQuery.isError?<Notice error={c.groupQuery.error} label="组信息更新失败，保留上次数据" retry={c.groupQuery.refetch}/>:null}
    {!c.directoryPage.items.some(item=>item.id===group.id)&&c.directoryQuery.data?<div className={styles.contextNotice}>当前组未显示在目录中。<button onClick={c.revealGroup}>{c.scope.query||c.scope.external!=='all'?'清除筛选并定位':'定位组'}</button></div>:null}
    <section aria-label="组基础信息"><h3 className={styles.sectionTitle}>基础信息</h3><dl className={styles.groupFields}>
      <div><dt>组 ID</dt><dd><button aria-label="复制组 ID" onClick={()=>{void c.copyId(group.id)}}>{group.id}<Copy/></button></dd></div><div><dt>外部组 ID</dt><dd>{group.external_id||<span className={styles.muted}>未填写</span>}</dd></div>
      <div><dt>创建时间</dt><dd>{group.created_at?formatGroupDate(group.created_at):'未记录'}</dd></div><div><dt>最近更新</dt><dd>{group.updated_at?formatGroupDate(group.updated_at):'未记录'}</dd></div>
    </dl></section>
    <section className={styles.membersSection} aria-label={`组成员 ${group.name}`}>
      <div className={styles.membersHeading}><h3>组成员 {c.membersQuery.data?<small>{c.members.length}</small>:null}</h3><span className={styles.spacer}/>{c.canManage?<Button variant="outline" disabled={Boolean(c.busy)||c.membersQuery.isPending||Boolean(c.membersQuery.isError&&!c.membersQuery.data)} data-groups-add onClick={event=>c.openAddition(event.currentTarget)}><UserPlus/>添加成员</Button>:null}</div>
      {c.membersQuery.isError?<Notice error={c.membersQuery.error} label="组成员获取失败" retry={c.membersQuery.refetch}/>:null}
      {c.identitiesQuery.isError?<div className={styles.identityNotice}>成员名称暂未取得，当前显示成员 ID。<button onClick={()=>{void c.identitiesQuery.refetch()}}>重新读取名称</button></div>:null}
      {c.members.length||c.scope.memberQuery?<SearchInput aria-label="搜索组成员" value={c.scope.memberQuery} onValueChange={memberQuery=>c.updateScope({memberQuery,memberPage:1})} placeholder="搜索姓名、邮箱或成员 ID" inputClassName={styles.memberSearch} containerClassName={styles.memberSearchWrap}/>:null}
      {c.membersQuery.isPending?<p className={styles.inlineState} role="status">正在读取组成员…</p>:c.membersPage.items.length?<div className={styles.tableWrap}><table className={styles.memberTable} aria-label={`${group.name} 的成员`}><thead><tr><th scope="col">成员</th><th scope="col" className={styles.idColumn}>成员 ID</th><th scope="col">加入时间</th><th scope="col">操作</th></tr></thead><tbody>{c.membersPage.items.map(member=>{
        const who=memberIdentity(member.user_id,c.identities)
        return <tr key={member.user_id}><th scope="row"><div className={styles.memberIdentity}><span className={styles.avatar} aria-hidden="true">{Array.from(who.label)[0]}</span><span><strong>{who.label}</strong>{who.email&&who.email!==who.label?<small>{who.email}</small>:null}</span></div></th><td className={styles.idColumn}><button className={styles.idCopy} aria-label={`复制成员 ID ${member.user_id}`} onClick={()=>{void c.copyId(member.user_id)}}>{member.user_id}</button></td><td className={styles.joined}><time dateTime={member.created_at} title={formatGroupDate(member.created_at)}><span>{formatGroupDate(member.created_at)}</span><span>{formatGroupDate(member.created_at).split(' ')[0]}</span></time></td><td><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" disabled={Boolean(c.busy)} data-group-member-action={member.user_id} aria-label={`成员操作 ${who.label}`}><MoreHorizontal/></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={()=>{void c.copyId(member.user_id)}}><Copy/>复制成员 ID</DropdownMenuItem>{c.canManage?<><DropdownMenuSeparator/><DropdownMenuItem onSelect={()=>{void c.removeMember(member.user_id)}} className="text-destructive"><Trash2/>从组中移除</DropdownMenuItem></>:null}</DropdownMenuContent></DropdownMenu></td></tr>
      })}</tbody></table></div>:!c.membersQuery.isError?<div className={styles.inlineState}><p>{c.scope.memberQuery?'没有匹配的成员。':'该组还没有成员。'}</p>{c.scope.memberQuery?<Button variant="ghost" onClick={()=>c.updateScope({memberQuery:'',memberPage:1})}>清除成员搜索</Button>:null}</div>:null}
      {c.membersPage.pages>1?<div className={styles.memberPager}><span>共 {c.membersPage.total} 名成员</span><span className={styles.spacer}/><Button variant="ghost" size="icon" aria-label="上一页成员" disabled={c.membersPage.page<=1} onClick={()=>c.updateScope({memberPage:c.membersPage.page-1})}><ChevronLeft/></Button><span>{c.membersPage.page} / {c.membersPage.pages}</span><Button variant="ghost" size="icon" aria-label="下一页成员" disabled={c.membersPage.page>=c.membersPage.pages} onClick={()=>c.updateScope({memberPage:c.membersPage.page+1})}><ChevronRight/></Button></div>:null}
    </section>
  </section>
}

export default function GroupWorkspace() {
  const c=useGroupDirectory()
  return <AppFrame><section className={styles.workspace} data-groups-directory data-view={c.scope.view}>
    <header className={styles.header}><div className={styles.heading}><PageTitleIcon name="group-management"/><h1>组管理</h1></div><div className={styles.headerActions}><Button variant="ghost" aria-label="刷新组" disabled={c.refreshing||Boolean(c.busy)} onClick={()=>{void c.refresh()}}>{c.refreshing?<Loader2 className="animate-spin motion-reduce:animate-none"/>:<RefreshCw/>}<span>刷新组</span></Button>{c.canManage?<Button className={styles.primary} data-groups-create disabled={Boolean(c.busy)} onClick={event=>c.openEditor('create',event.currentTarget)}><Plus/><span>新建组</span></Button>:null}</div></header>
    <div className={styles.body}><GroupDirectory controller={c}/><GroupDetails controller={c}/></div>
    <footer className={styles.footer}><span>{c.directoryQuery.isError?'组目录读取失败':c.directoryQuery.isPending?'正在读取组目录':c.scope.query||c.scope.external!=='all'?`组目录 · ${c.directoryPage.total} / ${c.groups.length} 个组`:`共 ${c.groups.length} 个组`}</span><span className={styles.spacer}/>{c.directoryPage.total>0?<><Select value={String(c.scope.size)} onValueChange={size=>c.updateScope({size:Number(size),page:1})}><SelectTrigger aria-label="组目录每页数量" className={styles.pageSize}><SelectValue/></SelectTrigger><SelectContent>{[10,20,50].map(size=><SelectItem key={size} value={String(size)}>每页 {size} 个组</SelectItem>)}</SelectContent></Select><Button variant="ghost" size="icon" aria-label="上一页组" disabled={c.directoryPage.page<=1} onClick={()=>c.updateScope({page:c.directoryPage.page-1})}><ChevronLeft/></Button><span>{c.directoryPage.page} / {c.directoryPage.pages}</span><Button variant="ghost" size="icon" aria-label="下一页组" disabled={c.directoryPage.page>=c.directoryPage.pages} onClick={()=>c.updateScope({page:c.directoryPage.page+1})}><ChevronRight/></Button></>:null}</footer>
    <GroupDialogs controller={c}/>
  </section></AppFrame>
}
