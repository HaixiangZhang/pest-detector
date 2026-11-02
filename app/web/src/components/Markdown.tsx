/**
 * Markdown — 轻量 Markdown 渲染（零依赖，离线可用）。
 *
 * 只需覆盖仓库文档用到的语法: 标题 / 段落 / 列表 / 表格 / 代码块 / 引用 /
 * 分隔线 / 粗体 / 行内代码 / 链接 / 图片。不追求完整 CommonMark，
 * 但足以把 README 与 docs/*.md 渲染到网页上。
 */

import type { ReactNode } from 'react'

type Block =
  | { type: 'heading'; level: number; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'list'; ordered: boolean; items: string[] }
  | { type: 'table'; header: string[]; rows: string[][] }
  | { type: 'code'; lang: string; text: string }
  | { type: 'quote'; text: string }
  | { type: 'divider' }

const HEADING_REGEX = /^(#{1,6})\s+(.*)$/
const LIST_REGEX = /^\s*([-*+]|\d+\.)\s+/
const DIVIDER_REGEX = /^\s{0,3}([-*_])(\s?\1){2,}\s*$/

function splitRow(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim())
}

function isTableSeparator(line: string): boolean {
  return /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$/.test(line.trim())
}

/** 预处理: 去掉 README 里少数几个 HTML 标签（<details>/<summary>/<br>）。 */
function preprocess(source: string): string {
  return source
    .replace(/\r\n/g, '\n')
    .replace(/<\/?details>/g, '')
    .replace(/<\/?summary>/g, '')
    .replace(/<br\s*\/?>/g, '\n')
}

function parse(source: string): Block[] {
  const lines = preprocess(source).split('\n')
  const blocks: Block[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) { i += 1; continue }

    if (line.trimStart().startsWith('```')) {
      const lang = line.trim().slice(3).trim()
      const body: string[] = []
      i += 1
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) {
        body.push(lines[i]); i += 1
      }
      i += 1
      blocks.push({ type: 'code', lang, text: body.join('\n') })
      continue
    }

    const heading = HEADING_REGEX.exec(line)
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2].trim() })
      i += 1
      continue
    }

    if (DIVIDER_REGEX.test(line)) {
      blocks.push({ type: 'divider' })
      i += 1
      continue
    }

    if (line.trimStart().startsWith('|')) {
      const rows: string[][] = []
      while (i < lines.length && lines[i].trimStart().startsWith('|')) {
        rows.push(splitRow(lines[i])); i += 1
      }
      const hasSeparator = rows.length > 1 && isTableSeparator(lines[i - rows.length + 1])
      blocks.push({
        type: 'table',
        header: rows[0],
        rows: rows.slice(hasSeparator ? 2 : 1),
      })
      continue
    }

    if (LIST_REGEX.test(line)) {
      const ordered = /^\s*\d+\./.test(line)
      const items: string[] = []
      while (i < lines.length && LIST_REGEX.test(lines[i])) {
        let item = lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, '').trim()
        i += 1
        // 缩进续行并入当前条目
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !LIST_REGEX.test(lines[i])) {
          item += ' ' + lines[i].trim(); i += 1
        }
        items.push(item)
      }
      blocks.push({ type: 'list', ordered, items })
      continue
    }

    if (line.trimStart().startsWith('>')) {
      const body: string[] = []
      while (i < lines.length && lines[i].trimStart().startsWith('>')) {
        body.push(lines[i].trimStart().replace(/^>\s?/, '')); i += 1
      }
      blocks.push({ type: 'quote', text: body.join('\n') })
      continue
    }

    const body: string[] = []
    while (
      i < lines.length && lines[i].trim() &&
      !HEADING_REGEX.test(lines[i]) && !lines[i].trimStart().startsWith('```') &&
      !lines[i].trimStart().startsWith('|') && !LIST_REGEX.test(lines[i]) &&
      !lines[i].trimStart().startsWith('>')
    ) {
      body.push(lines[i].trim()); i += 1
    }
    blocks.push({ type: 'paragraph', text: body.join(' ') })
  }
  return blocks
}

const INLINE_REGEX = /(!?\[[^\]]*\]\([^)\s]+\)|`[^`]+`|\*\*[^*]+\*\*|https?:\/\/[^\s<>)]+)/g

function inlineNodes(text: string, key: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let last = 0
  let index = 0
  let match: RegExpExecArray | null
  INLINE_REGEX.lastIndex = 0
  while ((match = INLINE_REGEX.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index))
    const token = match[0]
    const k = `${key}-${index}`
    if (token.startsWith('![')) {
      const parts = /^!\[([^\]]*)\]\(([^)]+)\)$/.exec(token)
      if (parts && /^https?:/.test(parts[2])) {
        nodes.push(<img key={k} alt={parts[1]} src={parts[2]}
                          style={{ maxWidth: '100%', borderRadius: 6, margin: '8px 0' }} />)
      } else {
        nodes.push(parts ? parts[1] : token)
      }
    } else if (token.startsWith('`')) {
      nodes.push(
        <code key={k} style={{
          background: '#f1f5f9', color: '#0f172a', padding: '1px 5px',
          borderRadius: 4, fontSize: '0.9em', fontFamily: 'Consolas, monospace',
        }}>
          {token.slice(1, -1)}
        </code>,
      )
    } else if (token.startsWith('**')) {
      nodes.push(<strong key={k}>{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('[')) {
      const parts = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token)
      nodes.push(
        <a key={k} href={parts?.[2]} target="_blank" rel="noreferrer">{parts?.[1]}</a>,
      )
    } else {
      nodes.push(<a key={k} href={token} target="_blank" rel="noreferrer">{token}</a>)
    }
    last = match.index + token.length
    index += 1
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

const HEADING_SIZE: Record<number, number> = { 1: 22, 2: 18, 3: 16, 4: 15, 5: 14, 6: 14 }

export default function Markdown({ content }: { content: string }) {
  const blocks = parse(content)
  return (
    <div style={{ fontSize: 14, lineHeight: 1.8, color: '#1f2937', wordBreak: 'break-word' }}>
      {blocks.map((block, blockIndex) => {
        const key = `b${blockIndex}`
        switch (block.type) {
          case 'heading':
            return (
              <h3 key={key} style={{
                fontSize: HEADING_SIZE[block.level] ?? 14,
                margin: block.level === 1 ? '0 0 16px' : '24px 0 10px',
                fontWeight: 600, color: '#0f172a',
              }}>
                {inlineNodes(block.text, key)}
              </h3>
            )
          case 'paragraph':
            return <p key={key} style={{ margin: '10px 0' }}>{inlineNodes(block.text, key)}</p>
          case 'list':
            return block.ordered ? (
              <ol key={key} style={{ margin: '10px 0', paddingLeft: 22 }}>
                {block.items.map((item, itemIndex) => (
                  <li key={`${key}-${itemIndex}`} style={{ margin: '4px 0' }}>
                    {inlineNodes(item, `${key}-${itemIndex}`)}
                  </li>
                ))}
              </ol>
            ) : (
              <ul key={key} style={{ margin: '10px 0', paddingLeft: 22 }}>
                {block.items.map((item, itemIndex) => (
                  <li key={`${key}-${itemIndex}`} style={{ margin: '4px 0' }}>
                    {inlineNodes(item, `${key}-${itemIndex}`)}
                  </li>
                ))}
              </ul>
            )
          case 'table':
            return (
              <div key={key} style={{ overflowX: 'auto', margin: '12px 0' }}>
                <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
                  <thead>
                    <tr>
                      {block.header.map((cell, cellIndex) => (
                        <th key={cellIndex} style={{
                          border: '1px solid #e5e7eb', background: '#f8fafc',
                          padding: '6px 10px', textAlign: 'left', whiteSpace: 'nowrap',
                        }}>
                          {inlineNodes(cell, `${key}-h${cellIndex}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        {block.header.map((_, cellIndex) => (
                          <td key={cellIndex} style={{
                            border: '1px solid #e5e7eb', padding: '6px 10px', verticalAlign: 'top',
                          }}>
                            {inlineNodes(row[cellIndex] ?? '', `${key}-${rowIndex}-${cellIndex}`)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          case 'code':
            return (
              <pre key={key} style={{
                background: '#0f172a', color: '#e2e8f0', padding: '12px 14px',
                borderRadius: 8, overflowX: 'auto', fontSize: 12.5, lineHeight: 1.65,
                margin: '12px 0',
              }}>
                <code>{block.text}</code>
              </pre>
            )
          case 'quote':
            return (
              <blockquote key={key} style={{
                margin: '12px 0', padding: '8px 14px', borderLeft: '3px solid #16a34a',
                background: '#f0fdf4', color: '#374151',
              }}>
                {inlineNodes(block.text, key)}
              </blockquote>
            )
          case 'divider':
            return <div key={key} style={{ borderTop: '1px solid #e5e7eb', margin: '20px 0' }} />
          default:
            return null
        }
      })}
    </div>
  )
}
