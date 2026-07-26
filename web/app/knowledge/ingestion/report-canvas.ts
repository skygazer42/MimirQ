export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export function buildSafeReportFilename(label: string, extension: string): string {
  const safe = String(label || 'ingestion-audit-report')
    .replace(/[\\/:*?"<>|]+/g, '_')
    .replace(/\s+/g, '_')
    .slice(0, 90)
  return `${safe || 'ingestion-audit-report'}${extension}`
}

export function waitForNextPaint(): Promise<void> {
  return new Promise((resolve) => {
    globalThis.window.requestAnimationFrame(() => {
      globalThis.window.requestAnimationFrame(() => resolve())
    })
  })
}

export function canvasToBlob(
  canvas: HTMLCanvasElement,
  type: string,
  quality?: number
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob)
        else reject(new Error('Report image encode failed'))
      },
      type,
      quality
    )
  })
}

export type CanvasReportCard = {
  label: string
  value: string
}

export type CanvasReportTable = {
  headers: string[]
  rows: string[][]
}

export type CanvasReportSection = {
  note: string
  table: CanvasReportTable | null
  title: string
}

export async function renderReportHtmlToJpeg(html: string, filename: string) {
  const iframe = document.createElement('iframe')
  iframe.setAttribute('aria-hidden', 'true')
  Object.assign(iframe.style, {
    border: '0',
    height: '1px',
    left: '-10000px',
    opacity: '0',
    pointerEvents: 'none',
    position: 'fixed',
    top: '0',
    width: '1760px',
  })
  document.body.appendChild(iframe)

  try {
    const frameLoaded = new Promise<void>((resolve, reject) => {
      const timeout = globalThis.window.setTimeout(() => {
        reject(new Error('Report frame load timeout'))
      }, 4000)
      iframe.onload = () => {
        globalThis.window.clearTimeout(timeout)
        resolve()
      }
    })
    iframe.srcdoc = html
    await frameLoaded

    const frameDocument = iframe.contentDocument
    if (!frameDocument) throw new Error('Report frame unavailable')

    await new Promise((resolve) => globalThis.window.setTimeout(resolve, 160))
    await frameDocument.fonts?.ready.catch(() => undefined)
    await waitForNextPaint()

    const getText = (
      selector: string,
      root: ParentNode = frameDocument
    ): string =>
      root.querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim() ??
      ''
    const readCards = (selector: string): CanvasReportCard[] =>
      Array.from(frameDocument.querySelectorAll<HTMLElement>(selector))
        .map((card) => ({
          label: getText('.metric-label, .kpi-label', card),
          value: getText('.metric-value, .kpi-value', card),
        }))
        .filter((card) => card.label || card.value)
    const readTable = (section: HTMLElement): CanvasReportTable | null => {
      const table = section.querySelector('table')
      if (!table) return null
      const headers = Array.from(table.querySelectorAll('thead th')).map(
        (cell) => cell.textContent?.trim() ?? ''
      )
      const rows = Array.from(table.querySelectorAll('tbody tr')).map((row) =>
        Array.from(row.querySelectorAll('td')).map(
          (cell) => cell.textContent?.replace(/\s+/g, ' ').trim() ?? ''
        )
      )
      return headers.length || rows.length ? { headers, rows } : null
    }
    const readSection = (titlePart: string): CanvasReportSection | null => {
      const section = Array.from(
        frameDocument.querySelectorAll<HTMLElement>('.section-card, .section')
      ).find((item) => getText('h2', item).includes(titlePart))
      if (!section) return null
      return {
        note: getText('.section-note, .notes', section),
        table: readTable(section),
        title: getText('h2', section),
      }
    }

    const title =
      getText('.report-header h1') ||
      getText('.title') ||
      frameDocument.title ||
      '入库预检报告'
    const subtitle = getText('.report-subtitle') || getText('.sub')
    const generatedAt = getText('.generated-at')
    const metricCards = readCards('.kpi-card')
    const fallbackCards = readCards('.grid .card')
    const kpiCards = metricCards.length
      ? metricCards
      : fallbackCards.slice(0, 8)
    const basisCards = readCards('.basis-card').length
      ? readCards('.basis-card')
      : fallbackCards.slice(8, 12)
    const riskSection = readSection('风险分布') ?? readSection('问题清单')
    const pocSection =
      readSection('入库抽样') ??
      readSection('建议 POC') ??
      readSection('代表性样本')
    const highRiskSection =
      readSection('高风险文件') ?? readSection('需复核样本')
    const sampleSection = readSection('当前页面样本')

    const width = 1760
    const margin = 36
    const gap = 16
    const contentWidth = width - margin * 2
    const pixelRatio = Math.min(
      2,
      Math.max(1, globalThis.window.devicePixelRatio || 1)
    )
    const canvas = document.createElement('canvas')
    const context = canvas.getContext('2d')
    if (!context) throw new Error('Report image canvas unavailable')

    const setFont = (size: number, weight: number | string = 400) => {
      context.font = `${weight} ${size}px"PingFang SC","Microsoft YaHei","Inter", sans-serif`
    }
    const roundRect = (
      x: number,
      y: number,
      rectWidth: number,
      rectHeight: number,
      radius: number
    ) => {
      context.beginPath()
      context.moveTo(x + radius, y)
      context.lineTo(x + rectWidth - radius, y)
      context.quadraticCurveTo(x + rectWidth, y, x + rectWidth, y + radius)
      context.lineTo(x + rectWidth, y + rectHeight - radius)
      context.quadraticCurveTo(
        x + rectWidth,
        y + rectHeight,
        x + rectWidth - radius,
        y + rectHeight
      )
      context.lineTo(x + radius, y + rectHeight)
      context.quadraticCurveTo(x, y + rectHeight, x, y + rectHeight - radius)
      context.lineTo(x, y + radius)
      context.quadraticCurveTo(x, y, x + radius, y)
      context.closePath()
    }
    const drawCardBase = (
      x: number,
      y: number,
      rectWidth: number,
      rectHeight: number,
      radius = 14
    ) => {
      context.save()
      context.shadowColor = 'rgba(15, 23, 42, 0.08)'
      context.shadowBlur = 26
      context.shadowOffsetY = 12
      context.fillStyle = 'rgba(255, 255, 255, 0.92)'
      roundRect(x, y, rectWidth, rectHeight, radius)
      context.fill()
      context.restore()
      context.strokeStyle = '#dfe7f2'
      context.lineWidth = 1
      roundRect(x, y, rectWidth, rectHeight, radius)
      context.stroke()
    }
    const drawTextLines = (
      text: string,
      x: number,
      y: number,
      maxWidth: number,
      lineHeight: number,
      maxLines = 2
    ): number => {
      if (!text) return y
      const chars = Array.from(text)
      const lines: string[] = []
      let current = ''
      for (const char of chars) {
        const next = `${current}${char}`
        if (context.measureText(next).width > maxWidth && current) {
          lines.push(current)
          current = char
          if (lines.length >= maxLines) break
        } else {
          current = next
        }
      }
      if (current && lines.length < maxLines) lines.push(current)
      lines.forEach((line, index) => {
        const suffix =
          index === maxLines - 1 &&
          chars.join('').length > lines.join('').length
            ? '...'
            : ''
        context.fillText(`${line}${suffix}`, x, y + index * lineHeight)
      })
      return y + Math.max(1, lines.length) * lineHeight
    }
    const drawMetricCard = (
      card: CanvasReportCard,
      index: number,
      x: number,
      y: number,
      rectWidth: number,
      rectHeight: number
    ) => {
      drawCardBase(x, y, rectWidth, rectHeight, 12)
      const tones = [
        '#1264e8',
        '#1264e8',
        '#334155',
        '#6d47e8',
        '#0ea5b7',
        '#6d47e8',
        '#1264e8',
        '#0ea5b7',
      ]
      const tone = tones[index % tones.length] ?? '#1264e8'
      context.fillStyle = `${tone}18`
      roundRect(x + 22, y + 24, 60, 60, 16)
      context.fill()
      setFont(12, 900)
      context.fillStyle = tone
      context.textAlign = 'center'
      context.textBaseline = 'middle'
      context.fillText(card.label.slice(0, 4).toUpperCase(), x + 52, y + 54)
      context.textAlign = 'left'
      context.textBaseline = 'alphabetic'
      setFont(14, 500)
      context.fillStyle = '#52627a'
      context.fillText(card.label, x + 102, y + 44)
      setFont(26, 900)
      context.fillStyle = '#0c1730'
      drawTextLines(card.value, x + 102, y + 78, rectWidth - 126, 28, 1)
    }
    const drawSection = (
      section: CanvasReportSection,
      x: number,
      y: number,
      rectWidth: number,
      options: { maxRows?: number } = {}
    ): number => {
      const table = section.table
      const rows = table?.rows.slice(0, options.maxRows ?? 8) ?? []
      const headers = table?.headers.length
        ? table.headers
        : (rows[0]?.map((_, index) => `列 ${index + 1}`) ?? [])
      const rowHeight = 48
      const tableHeight = headers.length
        ? 44 + Math.max(1, rows.length) * rowHeight
        : 58
      const noteHeight = section.note ? 22 : 0
      const rectHeight = 70 + noteHeight + tableHeight
      drawCardBase(x, y, rectWidth, rectHeight, 12)

      setFont(20, 800)
      context.fillStyle = '#0c1730'
      context.fillText(section.title, x + 20, y + 32)
      if (section.note) {
        setFont(13, 400)
        context.fillStyle = '#52627a'
        drawTextLines(section.note, x + 20, y + 56, rectWidth - 40, 18, 1)
      }

      const tableY = y + 50 + noteHeight
      context.fillStyle = '#ffffff'
      roundRect(x + 18, tableY, rectWidth - 36, tableHeight, 10)
      context.fill()
      context.strokeStyle = '#dfe7f2'
      context.stroke()

      if (!headers.length) {
        setFont(14, 500)
        context.fillStyle = '#52627a'
        context.fillText('暂无数据', x + 34, tableY + 34)
        return y + rectHeight
      }

      const tableWidth = rectWidth - 36
      const columnWidth = tableWidth / Math.max(1, headers.length)
      context.fillStyle = '#f8fbff'
      roundRect(x + 18, tableY, tableWidth, 44, 10)
      context.fill()
      setFont(12, 800)
      context.fillStyle = '#475569'
      headers.forEach((header, index) => {
        drawTextLines(
          header,
          x + 34 + index * columnWidth,
          tableY + 28,
          columnWidth - 24,
          14,
          1
        )
      })
      rows.forEach((row, rowIndex) => {
        const currentY = tableY + 44 + rowIndex * rowHeight
        context.strokeStyle = '#edf2f8'
        context.beginPath()
        context.moveTo(x + 18, currentY)
        context.lineTo(x + 18 + tableWidth, currentY)
        context.stroke()
        setFont(13, rowIndex === 0 ? 650 : 500)
        context.fillStyle = '#0c1730'
        row.slice(0, headers.length).forEach((cell, index) => {
          drawTextLines(
            cell || '-',
            x + 34 + index * columnWidth,
            currentY + 22,
            columnWidth - 24,
            16,
            2
          )
        })
      })
      if (!rows.length) {
        setFont(14, 500)
        context.fillStyle = '#52627a'
        context.fillText('暂无数据', x + 34, tableY + 82)
      }
      return y + rectHeight
    }

    const cardWidth = (contentWidth - gap * 3) / 4
    const kpiRows = Math.max(1, Math.ceil(kpiCards.length / 4))
    let height = margin + 92 + kpiRows * 124 + 20 + 190
    if (riskSection) height += 260
    if (pocSection || highRiskSection) height += 360
    if (sampleSection) height += 260
    height += margin

    canvas.width = Math.ceil(width * pixelRatio)
    canvas.height = Math.ceil(height * pixelRatio)
    context.scale(pixelRatio, pixelRatio)
    context.fillStyle = '#f5f8fc'
    context.fillRect(0, 0, width, height)
    const gradient = context.createLinearGradient(0, 0, 0, height)
    gradient.addColorStop(0, '#f8fbff')
    gradient.addColorStop(0.55, '#f5f8fc')
    gradient.addColorStop(1, '#eef4fb')
    context.fillStyle = gradient
    context.fillRect(0, 0, width, height)

    let y = margin
    setFont(40, 900)
    context.fillStyle = '#0c1730'
    context.fillText(title, margin, y + 28)
    setFont(15, 400)
    context.fillStyle = '#52627a'
    y = drawTextLines(subtitle, margin, y + 66, 1060, 22, 2)
    if (generatedAt) {
      setFont(12, 500)
      context.fillStyle = '#718096'
      context.fillText(generatedAt, margin, y + 8)
    }
    y += 34

    kpiCards.slice(0, 8).forEach((card, index) => {
      const col = index % 4
      const row = Math.floor(index / 4)
      drawMetricCard(
        card,
        index,
        margin + col * (cardWidth + gap),
        y + row * 124,
        cardWidth,
        108
      )
    })
    y += kpiRows * 124 + 12

    const basisSection: CanvasReportSection = {
      note: '面向入库前预检与确认入库，仅保留脱敏后的规模、体量和阻断线索。',
      table: null,
      title: '入库依据',
    }
    drawCardBase(margin, y, contentWidth, 178, 12)
    setFont(20, 800)
    context.fillStyle = '#0c1730'
    context.fillText(basisSection.title, margin + 20, y + 32)
    setFont(13, 400)
    context.fillStyle = '#52627a'
    context.fillText(basisSection.note, margin + 20, y + 56)
    basisCards.slice(0, 4).forEach((card, index) => {
      const x = margin + 18 + index * ((contentWidth - 36 - gap * 3) / 4 + gap)
      const w = (contentWidth - 36 - gap * 3) / 4
      drawMetricCard(card, index + 8, x, y + 80, w, 78)
    })
    y += 190

    if (riskSection)
      y = drawSection(riskSection, margin, y, contentWidth, { maxRows: 8 }) + 12
    if (pocSection || highRiskSection) {
      const splitWidth = (contentWidth - gap) / 2
      const leftEnd = pocSection
        ? drawSection(pocSection, margin, y, splitWidth, { maxRows: 5 })
        : y
      const rightEnd = highRiskSection
        ? drawSection(
            highRiskSection,
            margin + splitWidth + gap,
            y,
            splitWidth,
            { maxRows: 5 }
          )
        : y
      y = Math.max(leftEnd, rightEnd) + 12
    }
    if (sampleSection)
      y =
        drawSection(sampleSection, margin, y, contentWidth, { maxRows: 8 }) + 12

    const jpeg = await canvasToBlob(canvas, 'image/jpeg', 0.94)
    downloadBlob(jpeg, filename)
  } finally {
    iframe.remove()
  }
}
