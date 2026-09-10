import { useEffect, useState } from "react";
import {
  ApiError,
  getPlan,
  getPreviewTimeline,
  modifyPlan,
  type PlanDetail,
  type PreviewTimeline,
} from "./api";
import { PlanReview } from "./PlanReview";

export function App() {
  const parameters = new URLSearchParams(window.location.search);
  const projectId = parameters.get("project") ?? "";
  const assetId = parameters.get("asset") ?? "";
  const [plan, setPlan] = useState<PlanDetail | null>(null);
  const [preview, setPreview] = useState<PreviewTimeline | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!projectId || !assetId) return;
    const controller = new AbortController();
    Promise.all([
      getPlan(projectId, assetId, controller.signal),
      getPreviewTimeline(projectId, assetId, controller.signal),
    ])
      .then(([loadedPlan, loadedPreview]) => {
        setPlan(loadedPlan);
        setPreview(loadedPreview);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof ApiError ? reason.message : "无法读取剪辑计划");
      });
    return () => controller.abort();
  }, [projectId, assetId]);

  if (!projectId || !assetId) {
    return <main className="shell"><p role="status">请在地址中提供 project 和 asset 参数。</p></main>;
  }
  if (error) return <main className="shell"><p role="alert">{error}</p></main>;
  if (!plan || !preview) return <main className="shell"><p role="status">正在读取剪辑计划…</p></main>;
  return (
    <main className="shell">
      <PlanReview
        initialPlan={plan}
        initialPreview={preview}
        mediaUrl={`/api/projects/${encodeURIComponent(projectId)}/media/source/${encodeURIComponent(assetId)}`}
        saveDecision={async (segmentId, action) => {
          const updatedPlan = await modifyPlan(
            projectId,
            assetId,
            segmentId,
            action,
          );
          const updatedPreview = await getPreviewTimeline(projectId, assetId);
          return { plan: updatedPlan, preview: updatedPreview };
        }}
      />
    </main>
  );
}
