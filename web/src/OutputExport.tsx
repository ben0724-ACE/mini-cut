import { useEffect, useRef, useState } from "react";
import { startOutputExport, readOutputExport, recoverOutputExport, cancelOutputExport, type OutputExportTask, type OutputExportOptions } from "./api";
import { GeometrySettings } from "./GeometrySettings";

export function OutputExport({project,collection,output,revision}:{project:string;collection:string;output:string;revision:number}) {
  const [options,setOptions]=useState<OutputExportOptions>({subtitle_mode:"soft",audio_fade_ms:0,denoiser_id:"none"});
  const [task,setTask]=useState<OutputExportTask|null>(null); const [error,setError]=useState("");
  const [sending,setSending]=useState(false);const lock=useRef(false); const key=useRef<string|undefined>(undefined);
  const active=task?.status==="pending"||task?.status==="running";
  useEffect(()=>{const controller=new AbortController();recoverOutputExport(project,collection,output,controller.signal).then(value=>{if(!controller.signal.aborted)setTask(value);}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"恢复导出失败");});return()=>controller.abort();},[project,collection,output]);
  useEffect(()=>{if(!active||!task)return;const controller=new AbortController();const timer=setTimeout(()=>{readOutputExport(project,task.task_id,controller.signal).then(value=>{if(!controller.signal.aborted)setTask(value);}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"读取导出状态失败");});},1000);return()=>{controller.abort();clearTimeout(timer);};},[active,task,project]);
  function change(changes:Partial<OutputExportOptions>){key.current=undefined;setOptions({...options,...changes});}
  async function submit(){if(lock.current||active)return;lock.current=true;setSending(true);setError("");key.current??=crypto.randomUUID();try{setTask(await startOutputExport(project,collection,output,revision,options,key.current));key.current=undefined;}catch(reason){setError(reason instanceof Error?reason.message:"导出失败");}finally{lock.current=false;setSending(false);}}
  return <section aria-label="单作品导出"><details><summary>导出设置</summary>
    <GeometrySettings value={options} disabled={active||sending} onChange={change} />
    <label>字幕方式<select disabled={active||sending} value={options.subtitle_mode} onChange={event=>change({subtitle_mode:event.target.value as OutputExportOptions["subtitle_mode"]})}><option value="soft">软字幕（播放器可开关）</option><option value="burned">烧录字幕（画面内）</option></select></label>
    <label>切点淡入淡出（毫秒）<input type="number" min={0} max={500} disabled={active||sending} value={options.audio_fade_ms} onChange={event=>change({audio_fade_ms:Number(event.target.value)})} /></label>
    <label>降噪<select disabled={active||sending} value={options.denoiser_id} onChange={event=>change({denoiser_id:event.target.value as OutputExportOptions["denoiser_id"]})}><option value="none">关闭</option><option value="afftdn">FFmpeg 降噪</option></select></label>
    <p>不生成新语音；降噪与淡入淡出默认关闭。每次成功导出保留独立文件。</p></details>
    <button disabled={active||sending} onClick={()=>void submit()}>导出当前作品</button>
    {active&&<button onClick={()=>{setError("");void cancelOutputExport(project,task.task_id).then(()=>setError("已请求取消，等待后台停止")).catch(reason=>setError(reason instanceof Error?reason.message:"取消失败"));}}>取消导出</button>}
    {task&&<p role="status">导出状态：{task.status}{task.result&&` · 版本 ${task.result.revision}`}</p>}
    {(error||task?.error)&&<p role="alert">{error||task?.error}</p>}
    {task?.status==="succeeded"&&task.result&&<p><a href={task.result.media_url} download>下载视频</a> · <a href={task.result.subtitle_url} download>下载字幕</a></p>}
  </section>;
}
