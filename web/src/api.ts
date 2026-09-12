export interface PlanSegment {
  segment_id: string;
  text: string;
  start_ms: number;
  end_ms: number;
  action: "keep" | "delete";
  reason: string;
  confidence: number;
  explanation: string;
}

export interface PlanDetail {
  asset_id: string;
  revision: number;
  available_revisions: number[];
  summary: string;
  target_duration_ms: number;
  intensity: string;
  style: string;
  segments: PlanSegment[];
}

export interface PreviewClip {
  clip_id: string;
  segment_ids: string[];
  source_start_ms: number;
  source_end_ms: number;
  output_start_ms: number;
  output_end_ms: number;
}

export interface PreviewTimeline {
  asset_id: string;
  plan_revision: number;
  estimated_duration_ms: number;
  clips: PreviewClip[];
  jump_cut_risks: JumpCutRisk[];
}

export interface JumpCutRisk {
  left_clip_id: string;
  right_clip_id: string;
  removed_gap_ms: number;
  output_at_ms: number;
  explanation: string;
}

export class ApiError extends Error {}

export interface ProjectSummary { project_id: string; name?: string; asset_count: number }
export interface ProjectDetail extends ProjectSummary { asset_ids: string[] }
export interface AssetDetail { asset_id: string; name: string; duration_ms: number; has_transcript: boolean; has_plan: boolean }
export interface TranscriptionTask {task_id: string; status: "pending" | "running" | "succeeded" | "failed"; result: {word_count?: number; reused?: boolean} | null; error: string | null}
export interface TranscriptionOptions {provider: "mlx" | "whisper"; model: string; language: string}
export interface HighlightClip {instance_id: string; segment_id: string; role: string; text: string; start_ms: number; end_ms: number}
export interface HighlightOutput {output_id: string; title: string; reason: string; revision: number; duration_ms: number; clips: HighlightClip[]}
export interface HighlightResult {collection_id: string; asset_id: string; brief: import("./HighlightForm").HighlightBrief; notes: string[]; outputs: HighlightOutput[]; selected_output_ids?: string[]}
export const saveHighlightSelection = (project: string, collection: string, output_ids: string[]) => projectRequest<HighlightResult>(`/api/projects/${encodeURIComponent(project)}/highlights/${encodeURIComponent(collection)}/selection`, {method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({output_ids})});
export interface HighlightTask {task_id: string; status: TranscriptionTask["status"]; result: HighlightResult | null; error: string | null}
export const recoverHighlights = (project: string, asset: string, signal?: AbortSignal) => projectRequest<HighlightTask | null>(`/api/projects/${encodeURIComponent(project)}/assets/${encodeURIComponent(asset)}/highlight-task`, {signal});
export const readHighlightTask = (project: string, task: string, signal?: AbortSignal) => projectRequest<HighlightTask>(`/api/projects/${encodeURIComponent(project)}/tasks/${encodeURIComponent(task)}`, {signal});
export const startHighlights = (project: string, asset: string, brief: import("./HighlightForm").HighlightBrief, key: string) => projectRequest<HighlightTask>(`/api/projects/${encodeURIComponent(project)}/tasks/highlights`, {method: "POST", headers: {"Content-Type": "application/json", "Idempotency-Key": key}, body: JSON.stringify({asset_id: asset, ...brief})});
export const getHighlights = (project: string, collection: string, signal?: AbortSignal) => projectRequest<HighlightResult>(`/api/projects/${encodeURIComponent(project)}/highlights/${encodeURIComponent(collection)}`, {signal});
export const recoverTranscription = (project: string, asset: string, signal?: AbortSignal) => projectRequest<TranscriptionTask | null>(`/api/projects/${encodeURIComponent(project)}/assets/${encodeURIComponent(asset)}/transcription-task`, {signal});
export const readTranscription = (project: string, task: string, signal?: AbortSignal) => projectRequest<TranscriptionTask>(`/api/projects/${encodeURIComponent(project)}/tasks/${encodeURIComponent(task)}`, {signal});
export const startTranscription = (project: string, asset: string, options: TranscriptionOptions) => projectRequest<TranscriptionTask>(`/api/projects/${encodeURIComponent(project)}/tasks/transcribe`, {method: "POST", headers: {"Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID()}, body: JSON.stringify({asset_id: asset, ...options})});
export const listAssets = (id: string, signal?: AbortSignal) => projectRequest<AssetDetail[]>(`/api/projects/${encodeURIComponent(id)}/assets`, { signal });
export const uploadAsset = (id: string, file: File) => projectRequest<{asset_id: string}>(`/api/projects/${encodeURIComponent(id)}/assets?filename=${encodeURIComponent(file.name)}`, {method: "POST", body: file});

async function projectRequest<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new ApiError(typeof payload?.detail === "string" ? payload.detail : `项目请求失败（${response.status}）`);
  }
  return await response.json() as T;
}

export const listProjects = (signal?: AbortSignal) => projectRequest<ProjectSummary[]>("/api/projects", { signal });
export const createProject = (name: string) => projectRequest<ProjectDetail>("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
export const getProject = (projectId: string, signal?: AbortSignal) => projectRequest<ProjectDetail>(`/api/projects/${encodeURIComponent(projectId)}`, { signal });

export interface RenderDownload {
  media_url: string;
  subtitle_url: string;
  duration_ms: number;
}

interface TaskStatus {
  task_id: string;
  status: "pending" | "running" | "succeeded" | "failed";
  result: { duration_ms?: number } | null;
  error: string | null;
}

export async function getPlan(
  projectId: string,
  assetId: string,
  signal?: AbortSignal,
): Promise<PlanDetail> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/plans/${encodeURIComponent(assetId)}`,
    { signal },
  );
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new ApiError(payload?.detail ?? `请求失败（${response.status}）`);
  }
  return (await response.json()) as PlanDetail;
}

export async function modifyPlan(
  projectId: string,
  assetId: string,
  segmentId: string,
  action: "keep" | "delete",
): Promise<PlanDetail> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/plans/${encodeURIComponent(assetId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        restore_segment_ids: action === "keep" ? [segmentId] : [],
        delete_segment_ids: action === "delete" ? [segmentId] : [],
      }),
    },
  );
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new ApiError(payload?.detail ?? `修改失败（${response.status}）`);
  }
  return (await response.json()) as PlanDetail;
}

export async function getPreviewTimeline(
  projectId: string,
  assetId: string,
  signal?: AbortSignal,
): Promise<PreviewTimeline> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/plans/${encodeURIComponent(assetId)}/preview`,
    { signal },
  );
  if (!response.ok) throw new ApiError(`无法生成预览（${response.status}）`);
  return (await response.json()) as PreviewTimeline;
}

const wait = (milliseconds: number) =>
  new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));

export async function renderAndWait(
  projectId: string,
  assetId: string,
  outputName: string,
): Promise<RenderDownload> {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(outputName)) {
    throw new ApiError("输出文件名只能包含字母、数字、点、下划线和连字符");
  }
  const project = encodeURIComponent(projectId);
  const taskId = globalThis.crypto.randomUUID();
  const submitted = await fetch(`/api/projects/${project}/tasks/render`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": taskId,
    },
    body: JSON.stringify({ asset_id: assetId, output_name: outputName }),
  });
  if (!submitted.ok) throw new ApiError(`无法提交渲染任务（${submitted.status}）`);

  let task = (await submitted.json()) as TaskStatus;
  while (task.status === "pending" || task.status === "running") {
    await wait(500);
    const response = await fetch(`/api/projects/${project}/tasks/${taskId}`);
    if (!response.ok) throw new ApiError(`无法查询渲染进度（${response.status}）`);
    task = (await response.json()) as TaskStatus;
  }
  if (task.status === "failed") throw new ApiError(task.error ?? "渲染失败");
  if (typeof task.result?.duration_ms !== "number") {
    throw new ApiError("渲染任务没有返回有效结果");
  }
  const encodedOutput = encodeURIComponent(outputName);
  const subtitleName = outputName.includes(".")
    ? outputName.replace(/\.[^.]+$/, ".srt")
    : `${outputName}.srt`;
  return {
    media_url: `/api/projects/${project}/media/exports/${encodedOutput}`,
    subtitle_url: `/api/projects/${project}/media/exports/${encodeURIComponent(subtitleName)}`,
    duration_ms: task.result.duration_ms,
  };
}
