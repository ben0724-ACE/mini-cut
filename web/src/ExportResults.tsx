import { useEffect, useState } from "react";
import { cancelOutputExport, getHighlights, readOutputExport, resumeTask, type HighlightOutput, type OutputExportTask } from "./api";
import { replaceExportResults, type ExportLocationEntry } from "./exportNavigation";

interface ExportRow extends ExportLocationEntry {task:OutputExportTask|null}
const active=(task:OutputExportTask|null)=>task?.status==="pending"||task?.status==="running";
const statusText:Record<OutputExportTask["status"],string>={pending:"等待导出",running:"正在导出",succeeded:"导出完成",failed:"导出失败",cancelled:"已取消"};

export function ExportResults({project,collection,entries}:{project:string;collection:string;entries:ExportLocationEntry[]}) {
  const [rows,setRows]=useState<ExportRow[]>(()=>entries.map(entry=>({...entry,task:null})));
  const [outputs,setOutputs]=useState<HighlightOutput[]>([]);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState("");
  const identity=entries.map(entry=>`${entry.outputId}:${entry.taskId}`).join("|");

  useEffect(()=>{setRows(entries.map(entry=>({...entry,task:null})));},[identity]);
  useEffect(()=>{const controller=new AbortController();getHighlights(project,collection,controller.signal).then(result=>{if(!controller.signal.aborted)setOutputs(result.outputs);}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"无法读取作品信息");});return()=>controller.abort();},[project,collection]);
  useEffect(()=>{const controller=new AbortController();Promise.all(entries.map(async entry=>({...entry,task:await readOutputExport(project,entry.taskId,controller.signal)}))).then(value=>{if(!controller.signal.aborted)setRows(value);}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"无法读取导出任务");});return()=>controller.abort();},[project,identity]);
  const hasActive=rows.some(row=>active(row.task));
  useEffect(()=>{if(!hasActive)return;const controller=new AbortController();const timer=window.setTimeout(()=>{Promise.all(rows.map(async row=>active(row.task)?{...row,task:await readOutputExport(project,row.taskId,controller.signal)}:row)).then(value=>{if(!controller.signal.aborted)setRows(value);}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"刷新导出进度失败");});},1000);return()=>{window.clearTimeout(timer);controller.abort();};},[hasActive,project,rows]);

  async function resume(row:ExportRow){if(!row.task||busy)return;setBusy(row.taskId);setError("");try{const task=await resumeTask<OutputExportTask>(project,row.taskId);const next=rows.map(item=>item.taskId===row.taskId?{...item,taskId:task.task_id,task}:item);setRows(next);replaceExportResults(project,collection,next.map(({outputId,taskId})=>({outputId,taskId})));}catch(reason){setError(reason instanceof Error?reason.message:"恢复导出失败");}finally{setBusy("");}}
  async function cancel(row:ExportRow){if(!row.task||busy)return;setBusy(row.taskId);setError("");try{const task=await cancelOutputExport(project,row.taskId);setRows(previous=>previous.map(item=>item.taskId===row.taskId?{...item,task}:item));}catch(reason){setError(reason instanceof Error?reason.message:"取消导出失败");}finally{setBusy("");}}

  return <section className="export-results" aria-label="导出结果">
    <header className="export-results-header"><div><p className="eyebrow">发布素材包</p><h1>导出结果</h1><p className="muted">可以返回继续编辑或导出其他作品；这里的任务不会因此停止。</p></div><div className="export-results-actions"><button onClick={()=>window.history.back()}>返回上一页继续导出</button><a href={`?project=${encodeURIComponent(project)}`}>返回当前项目</a></div></header>
    {error&&<p role="alert">{error}</p>}
    <div className="export-result-grid">{rows.map(row=>{const output=outputs.find(item=>item.output_id===row.outputId);const task=row.task;const result=task?.result;const title=result?.title??output?.title??row.outputId;const socialCopy=result?.social_copy??output?.social_copy;return <article className="export-result-card" key={row.taskId}>
      <div className="export-result-media">{result?.media_url?<video controls preload="metadata" poster={result.cover_url} src={result.media_url} aria-label={`预览 ${title}`} />:result?.cover_url?<img src={result.cover_url} alt={`${title} 封面`} />:<div className="export-result-placeholder">{task?statusText[task.status]:"正在读取任务…"}</div>}</div>
      <div className="export-result-body"><div className="export-result-status"><span>{task?statusText[task.status]:"读取中"}</span>{result?.revision&&<span>版本 {result.revision}</span>}</div><h2>{title}</h2><section aria-label={`${title} 发布文案`}><h3>发布简介</h3>{socialCopy?<p className="social-copy">{socialCopy}</p>:<p className="muted">旧项目未生成发布文案；不会自动调用 AI 补写。</p>}</section>
      {task?.error&&<p role="alert">{task.error}</p>}
      <div className="export-downloads">{task?.status==="succeeded"&&result&&<><a href={result.media_url} download>下载视频</a>{result.cover_url?<a href={result.cover_url} download>下载封面</a>:<span className="muted">此旧导出没有封面</span>}<a href={result.subtitle_url} download>下载字幕</a></>}{active(task)&&<button disabled={busy===row.taskId} onClick={()=>void cancel(row)}>取消导出</button>}{(task?.status==="failed"||task?.status==="cancelled")&&task.resumable&&<button disabled={!!busy} onClick={()=>void resume(row)}>按原设置重新导出</button>}</div></div>
    </article>;})}</div>
  </section>;
}
