import { useEffect, useRef, useState } from "react";
import { recoverTranscription, readTranscription, startTranscription, resumeTask, cancelOutputExport, type TranscriptionTask, type TranscriptionOptions } from "./api";

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
    recover(project, asset, controller.signal).then(value => {if (!controller.signal.aborted) {setTask(value); if(value?.configuration)setOptions(value.configuration); setLoading(false);}}).catch((reason: unknown) => {if (!controller.signal.aborted) {setError(reason instanceof Error ? reason.message : "无法恢复任务"); setLoading(false);}});
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
    <p className="helper-text">本机转录 · 未缓存模型需联网下载</p>
    <details className="helper-details"><summary>转录说明</summary><p className="helper-text">需安装所选引擎。设置仅用于下次转录；刷新恢复任务结果，不恢复设置。</p></details>
    <button disabled={loading || submitting || active || !!error} onClick={submit}>{loading ? "正在恢复任务…" : submitting ? "正在提交…" : "开始转录"}</button>
    {error && <p role="alert">{error}<button onClick={() => {setError(""); setPaused(false); setLoading(true); setRetry(value => value + 1);}}>重试查询</button></p>}
    {task?.status === "failed" && <p role="alert">转录失败：{task.error}</p>}
    {(task?.status==="failed"||task?.status==="cancelled")&&task.resumable&&<button disabled={submitting} onClick={async()=>{setSubmitting(true);setError("");try{const resumed=await resumeTask<TranscriptionTask>(project,task.task_id);setTask(resumed);if(resumed.configuration)setOptions(resumed.configuration);setPaused(false);}catch(reason){setError(reason instanceof Error?reason.message:"恢复失败");}finally{setSubmitting(false);}}}>继续未完成的转录</button>}
    {task?.status==="cancelled"&&<p role="status">转录已取消，完成的分块已保留。</p>}
    {task?.progress?.total!=null&&<p role="status">已完成 {task.progress.completed} / {task.progress.total} 个转录块</p>}
    {task?.status === "succeeded" && <p role="status">转录完成：{task.result?.word_count ?? "未知数量"} 个词{task.result?.reused ? "（复用已有转录）" : ""}</p>}
    {active && <><p role="status">{task.status === "pending" ? "等待执行" : "正在转录"}{paused ? " · 已停止查询" : ""}</p><button onClick={() => setPaused(!paused)}>{paused ? "恢复查询" : "停止查询"}</button><button onClick={()=>void cancelOutputExport(project,task.task_id).catch(reason=>setError(reason instanceof Error?reason.message:"取消失败"))}>取消转录</button><p className="helper-text">取消将在当前分块结束后生效，已完成分块会保留。停止查询只暂停界面更新。</p></>}
  </div>;
}
