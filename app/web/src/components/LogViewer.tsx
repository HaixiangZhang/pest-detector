import { useEffect, useRef } from 'react'

/** 实时日志尾随（自动滚到底部）。 */
export default function LogViewer({ lines }: { lines: string[] }) {
  const ref = useRef<HTMLPreElement>(null)

  useEffect(() => {
    const node = ref.current
    if (node) node.scrollTop = node.scrollHeight
  }, [lines])

  return (
    <pre
      ref={ref}
      style={{
        margin: 0,
        padding: 12,
        height: 260,
        overflow: 'auto',
        background: '#1e1e1e',
        color: '#d4d4d4',
        fontSize: 12,
        lineHeight: 1.6,
        borderRadius: 6,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-all',
      }}
    >
      {lines.length ? lines.join('\n') : '（暂无日志）'}
    </pre>
  )
}