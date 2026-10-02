import { useEffect, useRef, useState, type ReactNode } from "react";
import { ExportSections } from "./ExportSections";
import { startOutputExport, readOutputExport, recoverOutputExport, cancelOutputExport, type OutputExportTask, type OutputExportOptions } from "./api";
import { ExportPresetControls } from "./ExportPresetControls";
import { exportSettingsRoute } from "./exportSettingsApi";
import { ExportDraftStatus, useExportDraft } from "./useExportDraft";
import { GeometrySettings } from "./GeometrySettings";

export function OutputExport({project,collection,output,revision,sourceUrl,sourceTime,onSubmitted,disabled=false,coverVersion,cover}:{project:string;collection:string;output:string;revision:number;sourceUrl?:string;sourceTime?:number;disabled?:boolean;coverVersion?:number;cover?:ReactNode;onSubmitted?:(entries:{outputId:string;taskId:string}[])=>void}) {
  const settings=useExportDraft(exportSettingsRoute(project,collection,output));
  const options=settings.draft.options;
  const settingsBlocked=!settings.loaded||!!settings.loadError;
  const [task,setTask]=useState<OutputExportTask|null>(null); const [error,setError]=useState("");
  const [recovering,setRecovering]=useState(true);const [query,setQuery]=useState(0);
  const [sending,setSending]=useState(false);const lock=useRef(false); const key=useRef<string|undefined>(undefined);
  const active=task?.status==="pending"||task?.status==="running";
  useEffect(()=>{const controller=new AbortController();setRecovering(true);recoverOutputExport(project,collection,output,controller.signal).then(value=>{if(!controller.signal.aborted)setTask(value);}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"恢复导出失败");}).finally(()=>{if(!controller.signal.aborted)setRecovering(false);});return()=>controller.abort();},[project,collection,output,query]);
  useEffect(()=>{if(!active||!task||error)return;const controller=new AbortController();const timer=setTimeout(()=>{readOutputExport(project,task.task_id,controller.signal).then(value=>{if(!controller.signal.aborted)setTask(value);}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"读取导出状态失败");});},1000);return()=>{controller.abort();clearTimeout(timer);};},[active,task,project,error]);
  function change(changes:Partial<typeof options>){key.current=undefined;settings.change({...settings.draft,options:{...options,...changes}});}
  async function submit(){if(disabled||lock.current||active||recovering||settingsBlocked||error)return;lock.current=true;setSending(true);setError("");key.current??=crypto.randomUUID();try{const submitted=await startOutputExport(project,collection,output,revision,{...options,cover_version:coverVersion},key.current);setTask(submitted);key.current=undefined;onSubmitted?.([{outputId:output,taskId:submitted.task_id}]);}catch(reason){setError(reason instanceof Error?reason.message:"导出失败");}finally{lock.current=false;setSending(false);}}
  return <section aria-label="单作品导出"><ExportSections cover={cover}><h2>导出设置</h2>
    <ExportPresetControls draft={settings.draft} onChange={draft=>{key.current=undefined;settings.change(draft);}} disabled={active||sending||settingsBlocked}/>
    <GeometrySettings sourceUrl={sourceUrl} sourceTime={sourceTime} value={options} disabled={active||sending||settingsBlocked} onChange={change} />
    <label>字幕方式<select disabled={active||sending||settingsBlocked} value={options.subtitle_mode} onChange={event=>change({subtitle_mode:event.target.value as OutputExportOptions["subtitle_mode"]})}><option value="soft">软字幕（播放器可开关）</option><option value="burned">烧录字幕（画面内）</option></select></label>
    <label>切点淡入淡出（毫秒）<input type="number" min={0} max={500} disabled={active||sending||settingsBlocked} value={options.audio_fade_ms} onChange={event=>change({audio_fade_ms:Number(event.target.value)})} /></label>
    <label>降噪<select disabled={active||sending||settingsBlocked} value={options.denoiser_id} onChange={event=>change({denoiser_id:event.target.value as OutputExportOptions["denoiser_id"]})}><option value="none">关闭</option><option value="afftdn">FFmpeg 降噪</option></select></label>
    <p className="helper-text">音频处理默认关闭，不生成新语音。每次导出独立保存。</p></ExportSections>
    <ExportDraftStatus state={settings}/>
    {disabled&&<p className="helper-text">请先保存或放弃封面修改，等待封面读取完成后导出。</p>}
    <button className="primary-button" disabled={disabled||active||sending||recovering||settingsBlocked||!!error} onClick={()=>void submit()}>导出当前作品</button>
    {active&&<button onClick={()=>{setError("");void cancelOutputExport(project,task.task_id).then(()=>setError("已请求取消，等待后台停止")).catch(reason=>setError(reason instanceof Error?reason.message:"取消失败"));}}>取消导出</button>}
    {task&&<p role="status">导出状态：{task.status}{task.result&&` · 版本 ${task.result.revision}`}</p>}
    {(error||task?.error)&&<p role="alert">{error||task?.error}</p>}
    {error&&<button onClick={()=>{setError("");setQuery(value=>value+1);}}>恢复导出状态</button>}
    {task&&onSubmitted&&<button onClick={()=>onSubmitted([{outputId:output,taskId:task.task_id}])}>查看导出结果页</button>}
    {task?.status==="succeeded"&&task.result&&<p><a href={task.result.media_url} download>下载视频</a> · <a href={task.result.subtitle_url} download>下载字幕</a></p>}
  </section>;
}
