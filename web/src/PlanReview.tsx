import type { PlanDetail } from "./api";

interface PlanReviewProps {
  plan: PlanDetail;
}

const formatTime = (milliseconds: number) =>
  new Date(milliseconds).toISOString().slice(14, 19);

export function PlanReview({ plan }: PlanReviewProps) {
  const kept = plan.segments.filter((segment) => segment.action === "keep").length;
  const deleted = plan.segments.length - kept;

  return (
    <section aria-labelledby="plan-title">
      <header className="plan-header">
        <div>
          <p className="eyebrow">Revision {plan.revision}</p>
          <h1 id="plan-title">文本审阅</h1>
          <p>{plan.summary}</p>
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
          </li>
        ))}
      </ol>
    </section>
  );
}
