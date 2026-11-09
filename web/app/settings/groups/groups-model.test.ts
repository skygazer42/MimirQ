import {describe,it,expect} from 'vitest'
import {filterGroups,formatGroupDate,groupDraft,memberIds,pageRows,parseGroupScope,readAll} from './groups-model'
import type {TenantGroupOut} from '@/types/backend'

describe('group-directory scope and safe writes',()=>{
  it('keeps absent and invalid timestamps distinct from a recent update',()=>{
    expect(formatGroupDate(null)).toBe('未记录')
    expect(formatGroupDate('not-a-date')).toBe('not-a-date')
    expect(formatGroupDate('2026-09-08T10:20:00+08:00')).toMatch(/2026-09-08.*\d{2}:\d{2}/)
  })
  it('restores a deep selection and rejects invalid page settings',()=>{
    expect(parseGroupScope('?group=g-2&q=研发&external=filled&size=50&page=3&mq=lin&mp=2')).toMatchObject({groupId:'g-2',query:'研发',external:'filled',size:50,page:3,memberQuery:'lin',memberPage:2,view:'detail'})
    expect(parseGroupScope('?size=999&page=-2&mp=NaN&external=connected')).toMatchObject({size:20,page:1,memberPage:1,external:'all'})
  })
  it('filters actual external-ID presence and searches IDs',()=>{
    const groups=[{id:'g-1',name:'研发',external_id:' idp-a '},{id:'g-2',name:'资料',external_id:''}] as TenantGroupOut[]
    expect(filterGroups(groups,{query:'IDP-A',external:'filled'}).map(g=>g.id)).toEqual(['g-1'])
    expect(filterGroups(groups,{query:'g-2',external:'empty'}).map(g=>g.id)).toEqual(['g-2'])
    expect(pageRows(groups,90,1)).toMatchObject({page:2,pages:2,items:[groups[1]]})
  })
  it('sends an explicit empty string to clear the backend external identifier',()=>{
    expect(groupDraft(' 研发 ','  ')).toEqual({errors:{},payload:{name:'研发',external_id:''}})
    expect(groupDraft('', 'x'.repeat(256)).errors).toHaveProperty('name')
    expect(groupDraft('组', 'x'.repeat(256)).errors).toHaveProperty('external')
  })
  it('deduplicates existing IDs and never silently truncates a batch',()=>{
    expect(memberIds(['a'],'a，b\nc;d')).toEqual({ids:['a','b','c','d'],error:''})
    expect(memberIds([],Array.from({length:201},(_,i)=>`m-${i}`).join('\n')).error).toContain('200')
    expect(memberIds([], 'x'.repeat(256)).error).toContain('255')
    expect(memberIds([], '  ').error).not.toBe('')
  })
  it('reads more than one API page without losing records',async()=>{
    const items=Array.from({length:507},(_,id)=>({id:String(id)})),skips:number[]=[]
    const all=await readAll(async(skip,limit)=>{skips.push(skip);return {items:items.slice(skip,skip+limit),total:items.length}},item=>item.id)
    expect(all).toHaveLength(507);expect(skips).toEqual([0,500])
  })
  it('rejects overlapping or inconsistent pagination instead of reporting an empty directory',async()=>{
    await expect(readAll<string>(async()=>({total:0}),item=>item)).resolves.toEqual([])
    await expect(readAll(async skip=>skip?{items:[{id:'a'}],total:2}:{items:[{id:'a'}],total:2},item=>item.id)).rejects.toThrow('重复')
    await expect(readAll(async()=>({items:[],total:1}),item=>String(item))).rejects.toThrow('不完整')
  })
})
