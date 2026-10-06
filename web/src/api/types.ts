// 与后端 API 对应的类型定义（字段以 result.json / Job.to_dict() 为准）

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export type DetectMode = 'sahi' | 'direct'

export interface Progress {
  done: number
  total: number
  elapsed: number
}

export interface JobSummary {
  unique_count: number | null
  raw_detections: number | null
  processed_frames: number | null
  elapsed_s: number | null
  snapshot_count: number
  has_video: boolean
  has_json: boolean
}

export interface Job {
  id: string
  status: JobStatus
  owner: string | null
  source: string
  mode: DetectMode
  params: Record<string, unknown>
  created_at: string
  started_at: string | null
  finished_at: string | null
  progress: Progress
  out_dir: string | null
  summary: JobSummary | null
  error: { code: string; message: string } | null
}

// SSE 事件（jobs/events.py 发布格式）
export interface JobEvent {
  type: 'status' | 'progress' | 'log' | 'done'
  status?: JobStatus
  done?: number
  total?: number
  elapsed?: number
  line?: string
  summary?: JobSummary
  error?: { code: string; message: string }
  processed?: number
  at?: string
}

export interface VideoItem {
  name: string
  path: string
  size_mb: number
  duration_s: number | null
}

export interface WeightItem {
  name: string
  path: string
  abs_path: string
  tag: string
  registered_at: string
  metrics: Record<string, number | string>
}

export interface PresetItem {
  name: string
  path: string
  /** 该预设显式覆盖的字段（增量，未写的沿用 configs.yaml）。 */
  params: Record<string, unknown>
}

/** 用户上传的源视频（持久化在 data/uploads/，刷新后仍在）。 */
export interface UploadItem {
  name: string
  path: string
  size_mb: number
  duration_s: number | null
  uploaded_at: number
  url: string
}

export interface FrameItem {
  name: string
  url: string
  size_kb: number
}

// 单条轨迹（result.json 的 tracks[]）
export interface TrackItem {
  id: number
  start_frame: number
  end_frame: number
  n_frames: number
  online_ids: number[]
  confidence_avg: number
  envelope: number[]
  path?: [number, number][]
}

export interface ResultJson {
  source: string
  source_name: string
  created_at: string
  model: string
  mode: DetectMode
  method: string
  video: {
    fps: number
    out_fps: number
    width: number
    height: number
    total_frames: number
    processed_frames: number
    frame_stride: number
  }
  counting: Record<string, number>
  tracks: TrackItem[]
  per_frame: { frame: number; n: number; ids: number[] }[]
  roi: Record<string, unknown>
  snapshots: { enabled: boolean; dir: string | null; count: number; items: unknown[] }
  config: Record<string, unknown>
  outputs: { video: string | null; json: string | null }
  elapsed_s: number
}