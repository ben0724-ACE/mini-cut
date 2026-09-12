import { useEffect, useRef, useState } from "react";
import { recoverHighlights, readHighlightTask, startHighlights, type AssetDetail, type HighlightTask } from "./api";
import { HighlightForm, type HighlightBrief } from "./HighlightForm";

export function HighlightPanel({project, asset, recover = recoverHighlights}: {project: string; asset: AssetDetail; recover?: typeof recoverHighlights}) {
  const [task, setTask] = useState<HighlightTask | null>(null);
  const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false); const [retry, setRetry] = useState(0);
  const lock = useRef(false); const identity = useRef<string | null>(null);
  const active = task?.status === "pending" || task?.status === "running";
  useEffect(() => {
    const controller = new AbortController();
    recover(project, asset.asset_id, controller.signal).then(value => {if (!controller.signal.aborted) {setTask(value); setLoading(false); if (value) identity.current = value.task_id;}}).catch((reason: unknown) => {if (!controller.signal.aborted) {setError(reason instanceof Error ? reason.message : "无法恢复生成任务"); setLoading(false);}});
    return () => controller.abort();
  }, [project, asset.asset_id, recover, retry]);
  useEffect(() => {
    if (!active || !task || error) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {readHighlightTask(project, task.task_id, controller.signal).then(value => {if (!controller.signal.aborted) setTask(value);}).catch((reason: unknown) => {if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "查询失败");});}, 1000);
    return () => {clearTimeout(timer); controller.abort();};
  }, [active, task, project, error]);
  async function submit(brief: HighlightBrief) {
    if (lock.current || active || loading || error) return;
    lock.current = true; setSubmitting(true);
    if (!identity.current || task?.status === "succeeded" || task?.status === "failed") identity.current = crypto.randomUUID();
    try {setTask(await startHighlights(project, asset.asset_id, brief, identity.current));}
    catch (reason: unknown) {setError(reason instanceof Error ? reason.message : "生成提交失败");}
    finally {lock.current = false; setSubmitting(false);}
  }
  return <section><h2>生成 · {asset.name}</h2><HighlightForm ready={asset.has_transcript} busy={loading || submitting || active || !!error} onSubmit={brief => void submit(brief)} />
    {error && <p role="alert">{error}<button onClick={() => {setError(""); setLoading(true); setRetry(value => value + 1);}}>恢复查询</button></p>}
    {active && <p role="status">{task.status === "pending" ? "等待 AI 生成" : "AI 正在生成"}；离开或刷新不会取消后台任务。</p>}
    {task?.status === "failed" && <p role="alert">生成失败：{task.error}。可修改要求后再次生成。</p>}
    {task?.status === "succeeded" && task.result && <section><p>源素材：{asset.name}</p>{task.result.notes.map((note, index) => <p key={index}>{note}</p>)}<div className="project-grid">{task.result.outputs.map(output => <article className="project-card" key={output.output_id}><h3>{output.title}</h3><p>{output.reason}</p><p>{(output.duration_ms / 1000).toFixed(2)} 秒 · 版本 {output.revision}</p></article>)}</div>{task.result.outputs.length === 0 && <p>没有符合要求的候选，请调整要求。</p>}</section>}
  </section>;
}
