import { useState } from "react";
import type { PlanDetail } from "./api";

interface PlanReviewProps {
  initialPlan: PlanDetail;
  saveDecision: (
    segmentId: string,
    action: "keep" | "delete",
  ) => Promise<PlanDetail>;
}

const formatTime = (milliseconds: number) =>
  new Date(milliseconds).toISOString().slice(14, 19);

interface UndoEntry {
  segmentId: string;
  previousAction: "keep" | "delete";
}

export function PlanReview({ initialPlan, saveDecision }: PlanReviewProps) {
  const [plan, setPlan] = useState(initialPlan);
  const [undoStack, setUndoStack] = useState<UndoEntry[]>([]);
  const [pendingSegment, setPendingSegment] = useState<string | null>(null);
  const [error, setError] = useState("");
  const kept = plan.segments.filter((segment) => segment.action === "keep").length;
  const deleted = plan.segments.length - kept;

  const changeDecision = async (
    segmentId: string,
    action: "keep" | "delete",
    remember: boolean,
  ): Promise<boolean> => {
    const segment = plan.segments.find((item) => item.segment_id === segmentId);
    if (!segment || segment.action === action) return false;
    setPendingSegment(segmentId);
    setError("");
    try {
      const updated = await saveDecision(segmentId, action);
      setPlan(updated);
      if (remember) {
        setUndoStack((entries) => [
          ...entries,
          { segmentId, previousAction: segment.action },
        ]);
      }
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法修改剪辑计划");
      return false;
    } finally {
      setPendingSegment(null);
    }
  };

  const undo = async () => {
    const entry = undoStack.at(-1);
    if (!entry) return;
    if (await changeDecision(entry.segmentId, entry.previousAction, false)) {
      setUndoStack((entries) => entries.slice(0, -1));
    }
  };

  return (
    <section aria-labelledby="plan-title">
      <header className="plan-header">
        <div>
          <p className="eyebrow">Revision {plan.revision}</p>
          <h1 id="plan-title">文本审阅</h1>
          <p>{plan.summary}</p>
          <button type="button" onClick={undo} disabled={!undoStack.length || pendingSegment !== null}>撤销上次修改</button>
          {error && <p role="alert">{error}</p>}
        </div>
        <dl className="plan-counts">
          <div><dt>保留</dt><dd>{kept}</dd></div>
          <div><dt>删除</dt><dd>{deleted}</dd></div>
        </dl>
      </header>
      <ol className="segments" aria-label="剪辑片段">
        {plan.segments.map((segment) => (
          <li className={`segment segment--${segment.action}`} key={segment.segment_id}>
            <div className="segment-meta">
              <span className="decision">{segment.action === "keep" ? "保留" : "删除"}</span>
              <time>{formatTime(segment.start_ms)}–{formatTime(segment.end_ms)}</time>
            </div>
            <p className="segment-text">{segment.text}</p>
            <p className="reason"><strong>{segment.reason}</strong> · {segment.explanation}</p>
            <button
              type="button"
              disabled={pendingSegment !== null}
              onClick={() => void changeDecision(
                segment.segment_id,
                segment.action === "keep" ? "delete" : "keep",
                true,
              )}
            >
              {pendingSegment === segment.segment_id
                ? "正在保存…"
                : segment.action === "keep" ? "删除此段" : "恢复此段"}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
