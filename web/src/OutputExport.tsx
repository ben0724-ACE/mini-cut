import { useEffect, useRef, useState, type ReactNode } from "react";
import { ExportSections } from "./ExportSections";
import { startOutputExport, readOutputExport, recoverOutputExport, cancelOutputExport, type OutputExportTask } from "./api";
import { OutputSettingsSummary } from "./OutputSettingsSummary";
import { exportSettingsRoute } from "./exportSettingsApi";
import { ExportDraftStatus, useExportDraft } from "./useExportDraft";

export function OutputExport({project,collection,output,revision,onAdjust,onSubmitted,disabled=false,coverVersion,cover,disabledReason}:{project:string;collection:string;output:string;revision:number;onAdjust?:(section:"frame"|"subtitles")=>void;disabled?:boolean;coverVersion?:number;cover?:ReactNode;disabledReason?:string;onSubmitted?:(entries:{outputId:string;taskId:string}[])=>void}) {
  const settings=useExportDraft(exportSettingsRoute(project,collection,output));
  const options=settings.draft.options;
  const settingsBlocked=!settings.loaded||!!settings.loadError;
  const [task,setTask]=useState<OutputExportTask|null>(null); const [error,setError]=useState("");
  const [recovering,setRecovering]=useState(true);const [query,setQuery]=useState(0);
  const [sending,setSending]=useState(false);const lock=useRef(false); const key=useRef<string|undefined>(undefined);
  const active=task?.status==="pending"||task?.status==="running";
  useEffect(()=>{const controller=new AbortController();setRecovering(true);recoverOutputExport(project,collection,output,controller.signal).then(value=>{if(!controller.signal.aborted)setTask(value);}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"恢复导出失败");}).finally(()=>{if(!controller.signal.aborted)setRecovering(false);});return()=>controller.abort();},[project,collection,output,query]);
  useEffect(()=>{if(!active||!task||error)return;const controller=new AbortController();const timer=setTimeout(()=>{readOutputExport(project,task.task_id,controller.signal).then(value=>{if(!controller.signal.aborted)setTask(value);}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"读取导出状态失败");});},1000);return()=>{controller.abort();clearTimeout(timer);};},[active,task,project,error]);
  const requestSettings=JSON.stringify({options,revision,coverVersion});
  useEffect(()=>{key.current=undefined;},[requestSettings]);
  async function submit(){if(disabled||lock.current||active||recovering||settingsBlocked||error)return;lock.current=true;setSending(true);setError("");key.current??=crypto.randomUUID();try{const submitted=await startOutputExport(project,collection,output,revision,{...options,cover_version:coverVersion},key.current);setTask(submitted);key.current=undefined;onSubmitted?.([{outputId:output,taskId:submitted.task_id}]);}catch(reason){setError(reason instanceof Error?reason.message:"导出失败");}finally{lock.current=false;setSending(false);}}
  return <section aria-label="单作品导出"><ExportSections cover={cover}><h2>最终画面设置</h2>
    {settings.loaded&&<OutputSettingsSummary options={options} presetName={settings.draft.preset_name}/>}
    {onAdjust&&<><button type="button" onClick={()=>onAdjust("frame")}>返回编辑调整画面</button><button type="button" onClick={()=>onAdjust("subtitles")}>返回编辑调整字幕</button></>}
    </ExportSections>
    <ExportDraftStatus state={settings}/>
    {disabled&&<p className="helper-text">{disabledReason??"请先保存或放弃封面修改，等待封面读取完成后导出。"}</p>}
    <button className="primary-button" disabled={disabled||active||sending||recovering||settingsBlocked||!!error} onClick={()=>void submit()}>导出当前作品</button>
    {active&&<button onClick={()=>{setError("");void cancelOutputExport(project,task.task_id).then(()=>setError("已请求取消，等待后台停止")).catch(reason=>setError(reason instanceof Error?reason.message:"取消失败"));}}>取消导出</button>}
    {task&&<p role="status">导出状态：{task.status}{task.result&&` · 版本 ${task.result.revision}`}</p>}
    {(error||task?.error)&&<p role="alert">{error||task?.error}</p>}
    {error&&<button onClick={()=>{setError("");setQuery(value=>value+1);}}>恢复导出状态</button>}
    {task&&onSubmitted&&<button onClick={()=>onSubmitted([{outputId:output,taskId:task.task_id}])}>查看导出结果页</button>}
    {task?.status==="succeeded"&&task.result&&<p><a href={task.result.media_url} download>下载视频</a> · <a href={task.result.subtitle_url} download>下载字幕</a></p>}
  </section>;
}
