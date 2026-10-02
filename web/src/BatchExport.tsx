import { BatchCoverTemplates } from "./BatchCoverTemplates";
import { ExportPresetControls } from "./ExportPresetControls";
import { exportSettingsRoute } from "./exportSettingsApi";
import { ExportDraftStatus, useExportDraft } from "./useExportDraft";
import { ExportSections } from "./ExportSections";
import { useEffect, useRef, useState } from "react";
import { GeometrySettings, type GeometryOptions } from "./GeometrySettings";
import { startOutputExportBatch, startOutputExport, recoverOutputExport, readOutputExport, type OutputExportOptions, type OutputExportTask } from "./api";
type Output = {output_id:string;title:string;revision:number};
export function BatchExport({project,collection,outputs,selected,disabled,onSubmitted}:{project:string;collection:string;outputs:Output[];selected:string[];disabled:boolean;onSubmitted?:(entries:{outputId:string;taskId:string}[])=>void}) {
  const [tasks,setTasks]=useState<Record<string,OutputExportTask>>({}); const [error,setError]=useState("");
  const [templateApplying,setTemplateApplying]=useState(false);
  const [sending,setSending]=useState(false); const lock=useRef(false); const key=useRef<string|undefined>(undefined);
  const [recovering,setRecovering]=useState(true);const [query,setQuery]=useState(0);
  const retryKeys=useRef<Record<string,string>>({});
  const settings=useExportDraft(exportSettingsRoute(project,collection));
  const {options,overrides}=settings.draft;
  const settingsBlocked=!settings.loaded||!!settings.loadError;
  function setOptions(next:typeof options){settings.change({...settings.draft,options:next});}
  function setOverrides(next:Record<string,GeometryOptions>){settings.change({...settings.draft,overrides:next});}
  const active=Object.values(tasks).some(task=>task.status==="pending"||task.status==="running");
  const resultEntries=outputs.flatMap(output=>tasks[output.output_id]?[{outputId:output.output_id,taskId:tasks[output.output_id].task_id}]:[]);
  useEffect(()=>{key.current=undefined;retryKeys.current={};},[selected,options,overrides]);
  useEffect(()=>{const controller=new AbortController();setRecovering(true);Promise.all(outputs.map(async output=>[output.output_id,await recoverOutputExport(project,collection,output.output_id,controller.signal)] as const)).then(rows=>{if(!controller.signal.aborted)setTasks(Object.fromEntries(rows.filter((row):row is readonly [string,OutputExportTask]=>row[1]!==null)));}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"恢复导出失败");}).finally(()=>{if(!controller.signal.aborted)setRecovering(false);});return()=>controller.abort();},[project,collection,outputs,query]);
  useEffect(()=>{if(!active)return;const controller=new AbortController();const timer=setTimeout(()=>{Promise.all(Object.entries(tasks).filter(([,task])=>task.status==="pending"||task.status==="running").map(async([id,task])=>[id,await readOutputExport(project,task.task_id,controller.signal)] as const)).then(rows=>{if(!controller.signal.aborted)setTasks(previous=>({...previous,...Object.fromEntries(rows)}));}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"读取导出失败");});},1000);return()=>{controller.abort();clearTimeout(timer);};},[tasks,active,project]);
  async function submit(output?:Output){if(lock.current||active||disabled||templateApplying||recovering||settingsBlocked)return;lock.current=true;setSending(true);setError("");try{
    if(output){retryKeys.current[output.output_id]??=crypto.randomUUID();const task=await startOutputExport(project,collection,output.output_id,output.revision,{...options,...overrides[output.output_id]},retryKeys.current[output.output_id]);delete retryKeys.current[output.output_id];setTasks(previous=>({...previous,[output.output_id]:task}));}
    else {const chosen=outputs.filter(output=>selected.includes(output.output_id));key.current??=crypto.randomUUID();const rows=await startOutputExportBatch(project,collection,chosen,options,key.current,overrides);setTasks(previous=>({...previous,...Object.fromEntries(chosen.map((output,index)=>[output.output_id,rows[index]]))}));key.current=undefined;onSubmitted?.(chosen.map((output,index)=>({outputId:output.output_id,taskId:rows[index].task_id})));}
  }catch(reason){setError(reason instanceof Error?reason.message:"提交导出失败");}finally{lock.current=false;setSending(false);}}
  return <section aria-label="批量导出"><ExportSections cover={<BatchCoverTemplates project={project} collection={collection} outputs={outputs} selected={selected} disabled={disabled||active||sending||recovering} onBusy={setTemplateApplying}/> }><h2>批量导出设置</h2><ExportPresetControls draft={settings.draft} onChange={settings.change} disabled={active||sending||settingsBlocked} batch/><><label>批量字幕<select disabled={active||sending||settingsBlocked} value={options.subtitle_mode} onChange={event=>{key.current=undefined;setOptions({...options,subtitle_mode:event.target.value as OutputExportOptions["subtitle_mode"]});}}><option value="soft">软字幕</option><option value="burned">烧录字幕</option></select></label><label>批量淡入淡出（毫秒）<input type="number" min={0} max={500} value={options.audio_fade_ms} disabled={active||sending||settingsBlocked} onChange={event=>{key.current=undefined;setOptions({...options,audio_fade_ms:Number(event.target.value)});}} /></label><label>批量降噪<select disabled={active||sending||settingsBlocked} value={options.denoiser_id} onChange={event=>{key.current=undefined;setOptions({...options,denoiser_id:event.target.value as OutputExportOptions["denoiser_id"]});}}><option value="none">关闭</option><option value="afftdn">FFmpeg 降噪</option></select></label></>
    <GeometrySettings label="批量" value={options} disabled={active||sending||settingsBlocked} onChange={geometry=>setOptions({...options,...geometry})} />
    <details><summary>逐条画幅覆盖</summary>{outputs.filter(output=>selected.includes(output.output_id)).map(output=><div key={output.output_id}><label><input type="checkbox" disabled={active||sending||settingsBlocked} checked={!!overrides[output.output_id]} onChange={event=>setOverrides((()=>{const next={...overrides};if(event.target.checked)next[output.output_id]={aspect_ratio:options.aspect_ratio??"original",resolution:options.resolution??1080,fit:options.fit??"pad",crop_left:options.crop_left,crop_right:options.crop_right,crop_top:options.crop_top,crop_bottom:options.crop_bottom};else delete next[output.output_id];return next;})())} />单独设置 {output.title}</label>{overrides[output.output_id]&&<GeometrySettings label={output.title} value={overrides[output.output_id]} disabled={active||sending||settingsBlocked} onChange={geometry=>setOverrides({...overrides,[output.output_id]:geometry})} />}</div>)}</details>
    <button type="button" disabled={active||sending||settingsBlocked||Object.keys(overrides).length===0} onClick={()=>setOverrides({})}>清除全部逐条覆盖</button>
    {Object.keys(overrides).length>0&&<p className="helper-text">已开启逐条覆盖的作品优先使用各自画幅，统一设置和预设不会覆盖它们。</p>}
    </ExportSections>
    <ExportDraftStatus state={settings}/>
    <button disabled={disabled||recovering||sending||active||templateApplying||settingsBlocked||selected.length===0} onClick={()=>void submit()}>导出已选作品</button><p className="helper-text">逐条导出，独立保存 · 刷新恢复进度</p><details><summary>导出说明</summary><p className="helper-text">导出不调用 AI。批次开始后，作品选择的变更仅用于下次导出。</p></details>
    {resultEntries.length>0&&onSubmitted&&<button onClick={()=>onSubmitted(resultEntries)}>查看全部导出结果</button>}
    {error&&<p role="alert">{error}<button onClick={()=>{setError("");setQuery(previous=>previous+1);}}>恢复状态查询</button></p>}
    <ul>{outputs.filter(output=>tasks[output.output_id]).map(output=>{const task=tasks[output.output_id];return <li key={output.output_id}>{output.title}：{task.status}{task.error&&` · ${task.error}`}{task.status==="succeeded"&&task.result&&<><a href={task.result.media_url} download>下载 {output.title}</a> · <a href={task.result.subtitle_url} download>字幕 {output.title}</a></>}{(task.status==="failed"||task.status==="cancelled")&&<button disabled={active||sending||disabled||templateApplying} onClick={()=>void submit(output)}>重试 {output.title}</button>}</li>;})}</ul>
  </section>;
}
