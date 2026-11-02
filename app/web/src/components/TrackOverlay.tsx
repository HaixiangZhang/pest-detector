import { useEffect, useRef } from 'react'
import type { RefObject } from 'react'

import type { ResultJson } from '../api/types'

/**
 * 轨迹叠加层：把 result.tracks[].path（逐帧中心点，原图像素坐标）按显示尺寸
 * 缩放后画成彩色折线，叠在 <video> 之上。
 *
 * 说明：这是**静态全轨迹**叠加（不随播放时间裁剪），用于一眼看清每只虫的运动
 * 路径与起点；坐标来自 result.json，无需后端额外产物。
 */
export default function TrackOverlay({
  result,
  videoRef,
  visible,
}: {
  result: ResultJson
  videoRef: RefObject<HTMLVideoElement>
  visible: boolean
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const video = videoRef.current
    if (!canvas || !video) return

    const draw = () => {
      const width = video.clientWidth
      const height = video.clientHeight
      if (!width || !height) return
      canvas.width = width
      canvas.height = height
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.clearRect(0, 0, width, height)
      if (!visible) return

      const videoWidth = result.video?.width || video.videoWidth || width
      const videoHeight = result.video?.height || video.videoHeight || height
      const scaleX = width / videoWidth
      const scaleY = height / videoHeight

      ctx.lineWidth = 2
      ctx.lineJoin = 'round'
      for (const track of result.tracks ?? []) {
        const path = track.path
        if (!path || path.length < 2) continue
        const color = `hsl(${(track.id * 47) % 360} 90% 55%)`
        ctx.strokeStyle = color
        ctx.beginPath()
        path.forEach(([x, y], index) => {
          const px = x * scaleX
          const py = y * scaleY
          if (index === 0) ctx.moveTo(px, py)
          else ctx.lineTo(px, py)
        })
        ctx.stroke()

        const [startX, startY] = path[0]
        ctx.fillStyle = color
        ctx.beginPath()
        ctx.arc(startX * scaleX, startY * scaleY, 3.5, 0, Math.PI * 2)
        ctx.fill()
      }
    }

    draw()
    const observer = new ResizeObserver(draw)
    observer.observe(video)
    return () => observer.disconnect()
  }, [result, videoRef, visible])

  return (
    <canvas
      ref={canvasRef}
      style={{ position: 'absolute', inset: 0, pointerEvents: 'none', borderRadius: 4 }}
    />
  )
}