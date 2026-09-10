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
