import { useEffect, useRef, useState } from "react";
import { recoverTranscription, readTranscription, startTranscription, type TranscriptionTask, type TranscriptionOptions } from "./api";

interface Props {project: string; asset: string; onComplete?: () => void; recover?: typeof recoverTranscription; read?: typeof readTranscription; start?: typeof startTranscription}
export function TranscriptionControls({project, asset, onComplete, recover = recoverTranscription, read = readTranscription, start = startTranscription}: Props) {
  const [options, setOptions] = useState<TranscriptionOptions>({provider: "mlx", model: "large-v3-turbo", language: "zh"});
  const [task, setTask] = useState<TranscriptionTask | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [paused, setPaused] = useState(false);
  const [retry, setRetry] = useState(0);
  const complete = useRef(onComplete); complete.current = onComplete;
  useEffect(() => {
    const controller = new AbortController();
    recover(project, asset, controller.signal).then(value => {if (!controller.signal.aborted) {setTask(value); setLoading(false);}}).catch((reason: unknown) => {if (!controller.signal.aborted) {setError(reason instanceof Error ? reason.message : "无法恢复任务"); setLoading(false);}});
    return () => controller.abort();
  }, [project, asset, recover, retry]);
  const active = task?.status === "pending" || task?.status === "running";
  useEffect(() => {
    if (!active || paused || !task) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      read(project, task.task_id, controller.signal).then(value => {if (!controller.signal.aborted) {setTask(value); if (value.status === "succeeded") complete.current?.();}}).catch((reason: unknown) => {if (!controller.signal.aborted) {setError(reason instanceof Error ? reason.message : "查询失败"); setPaused(true);}});
    }, 1000);
    return () => {clearTimeout(timer); controller.abort();};
  }, [task, active, paused, project, read]);
  async function submit() {
    if (active || loading || submitting) return;
    setSubmitting(true); setError(""); setPaused(false);
    try {const value = await start(project, asset, options); setTask(value); if (value.status === "succeeded") complete.current?.();}
    catch (reason: unknown) {setError(reason instanceof Error ? reason.message : "提交失败");}
    finally {setSubmitting(false);}
  }
  return <div className="transcription-controls">
    <label>转录引擎<select aria-label="转录引擎" disabled={active || submitting} value={options.provider} onChange={event => setOptions({...options, provider: event.target.value as TranscriptionOptions["provider"]})}><option value="mlx">MLX（Apple 芯片）</option><option value="whisper">PyTorch Whisper</option></select></label>
    <label>模型<select aria-label="模型" disabled={active || submitting} value={options.model} onChange={event => setOptions({...options, model: event.target.value})}>{["tiny", "base", "small", "medium", "large", "large-v2", "large-v3", "large-v3-turbo"].map(model => <option key={model}>{model}</option>)}</select></label>
    <label>语言<select aria-label="语言" disabled={active || submitting} value={options.language} onChange={event => setOptions({...options, language: event.target.value})}><option value="zh">中文</option><option value="en">英文</option></select></label>
    <p>使用本机模型；模型或引擎依赖未安装时会报告失败。未缓存模型可能需要联网下载。</p>
    <p>以上设置用于下一次转录；刷新恢复的是后台任务结果。</p>
    <button disabled={loading || submitting || active || !!error} onClick={submit}>{loading ? "正在恢复任务…" : submitting ? "正在提交…" : "开始转录"}</button>
    {error && <p role="alert">{error}<button onClick={() => {setError(""); setPaused(false); setLoading(true); setRetry(value => value + 1);}}>重试查询</button></p>}
    {task?.status === "failed" && <p role="alert">转录失败：{task.error}</p>}
    {task?.status === "succeeded" && <p role="status">转录完成：{task.result?.word_count ?? "未知数量"} 个词{task.result?.reused ? "（复用已有转录）" : ""}</p>}
    {active && <><p role="status">{task.status === "pending" ? "等待执行" : "正在转录"}{paused ? " · 已停止查询" : ""}</p><button onClick={() => setPaused(!paused)}>{paused ? "恢复查询" : "停止查询"}</button><p>停止查询或离开页面不会取消后台转录；刷新会找回任务。目前不支持取消后台计算。</p></>}
  </div>;
}
