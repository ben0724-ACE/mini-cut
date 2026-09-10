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
