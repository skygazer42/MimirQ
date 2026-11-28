// @vitest-environment happy-dom

import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { SplitEmptyStudio } from './split-empty-studio'

vi.stubGlobal('React', React)
vi.mock('@/i18n/navigation', () => ({ Link: 'a' }))

describe('shared empty workspace', () => {
  it('retains region labels, setup steps and the original action names', () => {
    const container = document.createElement('div')
    container.innerHTML = renderToStaticMarkup(
      <SplitEmptyStudio
        illustration={<svg />}
        title="还没有组"
        titleId="empty-title"
        description="创建协作团队"
        descriptionId="empty-description"
        role="region"
        ariaLabel="组详情"
        ariaDescribedBy="empty-description"
        dataAttributes={{ 'data-empty-groups': true }}
        actions={<button>创建第一个组</button>}
        stepsHeading="从团队开始"
        steps={[
          { index: '01', title: '组织协作团队', description: '创建清晰的目录。' },
          { index: '02', title: '映射外部标识', description: '按需填写标识。' },
          { index: '03', title: '维护成员清单', description: '添加已有成员。' },
        ]}
        shortcuts={[
          { key: 'knowledge', icon: <svg />, title: '知识库', description: '查看文档', href: '/knowledge' },
        ]}
      />,
    )
    const region = container.querySelector('section')!
    expect(region.getAttribute('role')).toBe('region')
    expect(region.getAttribute('aria-label')).toBe('组详情')
    expect(region.getAttribute('aria-describedby')).toBe('empty-description')
    expect(region.getAttribute('data-empty-groups')).toBe('true')
    expect(region.querySelector('#empty-title')?.textContent).toBe('还没有组')
    expect(region.querySelector('button')?.textContent).toBe('创建第一个组')
    expect(region.querySelector('aside')?.getAttribute('aria-label')).toBe('从团队开始')
    expect(region.querySelectorAll('ol > li')).toHaveLength(3)
    expect(region.querySelector('a')?.getAttribute('href')).toBe('/knowledge')
    expect(region.querySelector('a')?.textContent).toBe('知识库查看文档')
  })
})
