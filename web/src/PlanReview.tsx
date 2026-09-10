import { useRef, useState } from "react";
import type { PlanDetail, PreviewTimeline } from "./api";

interface PlanReviewProps {
  initialPlan: PlanDetail;
  initialPreview: PreviewTimeline;
  saveDecision: (
    segmentId: string,
    action: "keep" | "delete",
  ) => Promise<{ plan: PlanDetail; preview: PreviewTimeline }>;
  mediaUrl: string;
}

const formatTime = (milliseconds: number) =>
  new Date(milliseconds).toISOString().slice(14, 19);

const estimatedDuration = (plan: PlanDetail) =>
  plan.segments
    .filter((segment) => segment.action === "keep")
    .reduce((total, segment) => total + segment.end_ms - segment.start_ms, 0);

const formatDuration = (milliseconds: number) => {
  const seconds = Math.abs(milliseconds) / 1000;
  const minutes = Math.floor(seconds / 60);
  const remainder = (seconds % 60).toFixed(1).padStart(4, "0");
  return `${minutes.toString().padStart(2, "0")}:${remainder}`;
};

interface UndoEntry {
  segmentId: string;
  previousAction: "keep" | "delete";
}

export function PlanReview({
  initialPlan,
  initialPreview,
  saveDecision,
  mediaUrl,
}: PlanReviewProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const initialDuration = useRef(estimatedDuration(initialPlan));
  const [plan, setPlan] = useState(initialPlan);
  const [preview, setPreview] = useState(initialPreview);
  const [undoStack, setUndoStack] = useState<UndoEntry[]>([]);
  const [pendingSegment, setPendingSegment] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const kept = plan.segments.filter((segment) => segment.action === "keep").length;
  const deleted = plan.segments.length - kept;
  const duration = estimatedDuration(plan);
  const durationChange = duration - initialDuration.current;

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
      setPlan(updated.plan);
      setPreview(updated.preview);
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

  const seek = (milliseconds: number) => {
    if (videoRef.current) videoRef.current.currentTime = milliseconds / 1000;
  };

  const togglePlayback = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void video.play();
    else video.pause();
  };

  const startPreview = () => {
    const first = preview.clips[0];
    if (!first || !videoRef.current) return;
    videoRef.current.currentTime = first.source_start_ms / 1000;
    setPreviewing(true);
    void videoRef.current.play();
  };

  const followPreviewTimeline = () => {
    const video = videoRef.current;
    if (!previewing || !video) return;
    const sourceMs = video.currentTime * 1000;
    const clipIndex = preview.clips.findIndex(
      (clip) => sourceMs >= clip.source_start_ms && sourceMs < clip.source_end_ms,
    );
    if (clipIndex >= 0) return;
    const next = preview.clips.find((clip) => clip.source_start_ms > sourceMs);
    if (next) video.currentTime = next.source_start_ms / 1000;
    else {
      video.pause();
      setPreviewing(false);
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
      <div className="duration-summary" aria-live="polite">
        <span>预计输出时长</span>
        <strong>{formatDuration(duration)}</strong>
        <span className={durationChange > 0 ? "increase" : durationChange < 0 ? "decrease" : ""}>
          {durationChange === 0
            ? "暂无变化"
            : `${durationChange > 0 ? "+" : "−"}${formatDuration(durationChange)}`}
        </span>
      </div>
      <button type="button" className="preview-button" onClick={startPreview}>
        从头播放粗剪预览
      </button>
      <video
        ref={videoRef}
        className="player"
        controls
        preload="metadata"
        src={mediaUrl}
        onTimeUpdate={followPreviewTimeline}
      >
        浏览器无法播放这个视频。
      </video>
      <p className="keyboard-help">聚焦片段后：K 保留，D 删除，空格播放或暂停。</p>
      <ol className="segments" aria-label="剪辑片段">
        {plan.segments.map((segment) => (
          <li
            className={`segment segment--${segment.action}`}
            key={segment.segment_id}
            tabIndex={0}
            aria-label={`${segment.action === "keep" ? "保留" : "删除"}片段：${segment.text}`}
            onClick={(event) => {
              if ((event.target as HTMLElement).closest("button")) return;
              seek(segment.start_ms);
            }}
            onKeyDown={(event) => {
              const key = event.key.toLowerCase();
              if (key === "k") {
                void changeDecision(segment.segment_id, "keep", true);
              } else if (key === "d") {
                void changeDecision(segment.segment_id, "delete", true);
              } else if (event.key === " ") {
                event.preventDefault();
                seek(segment.start_ms);
                togglePlayback();
              } else if (event.key === "Enter") {
                seek(segment.start_ms);
              }
            }}
          >
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
