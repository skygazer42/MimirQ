import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { getQualityGateGrade, ParsingQualityNotice } from './parsing-quality-notice'

describe('parsing quality review', () => {
  it.each(['pass', 'warn', 'fail'] as const)('reads the %s grade used by the file status pill', (grade) => {
    expect(getQualityGateGrade({ grade })).toBe(grade)
  })

  it.each([undefined, null, [], 'pass', {}, { grade: 'unknown' }])(
    'does not treat unavailable quality evidence as a passed check: %j',
    (qualityGate) => {
      expect(getQualityGateGrade(qualityGate)).toBeNull()
    },
  )

  it.each([
    ['warn', '解析内容需要核对'],
    ['fail', '解析质量未通过检查'],
  ])('keeps %s review evidence collapsed until requested', (grade, label) => {
    const markup = renderToStaticMarkup(
      <ParsingQualityNotice qualityGate={{ grade, reasons: ['请核对表格结构'] }} pdfQuality={null} />,
    )

    expect(markup).toContain(label)
    expect(markup).toContain('请核对表格结构')
    expect(markup).toContain('<details')
    expect(markup).not.toContain(' open=')
  })
})
