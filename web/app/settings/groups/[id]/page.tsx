'use client'

import {useEffect,useRef} from 'react'
import {useParams} from 'next/navigation'
import {PageLoading} from '@/components/ui/page-loading'

export default function GroupDetailPage() {
  const {id}=useParams<{id:string}>(),navigating=useRef(false)
  useEffect(()=>{
    if(!id||navigating.current)return
    navigating.current=true
    window.location.replace(`/settings/groups?group=${encodeURIComponent(id)}`)
  },[id])
  return <PageLoading className="min-h-dvh bg-background" message="正在打开组…" srMessage="正在打开组目录"/>
}
