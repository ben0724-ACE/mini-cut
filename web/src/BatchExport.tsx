import { BatchCoverTemplates } from "./BatchCoverTemplates";
import { OutputSettingsControls } from "./OutputSettingsControls";
import { exportSettingsRoute, type ExportOptions } from "./exportSettingsApi";
import { ExportDraftStatus, useExportDraft } from "./useExportDraft";
import { ExportSections } from "./ExportSections";
import { useCallback, useEffect, useRef, useState } from "react";
import { GeometrySettings, type GeometryOptions } from "./GeometrySettings";
import { startOutputExportBatch, startOutputExport, recoverOutputExport, readOutputExport, type OutputExportTask } from "./api";
import {effectiveOutputOptions,OutputSettingsSummary} from "./OutputSettingsSummary";
type Output = {output_id:string;title:string;revision:number};
export function BatchExport({project,collection,outputs,selected,disabled,onSubmitted,onPreview}:{project:string;collection:string;outputs:Output[];selected:string[];disabled:boolean;onPreview?:(output:string)=>void;onSubmitted?:(entries:{outputId:string;taskId:string}[])=>void}) {
  const [tasks,setTasks]=useState<Record<string,OutputExportTask>>({}); const [error,setError]=useState("");
  const [templateApplying,setTemplateApplying]=useState(false);
  const [sending,setSending]=useState(false); const lock=useRef(false); const key=useRef<string|undefined>(undefined);
  const [recovering,setRecovering]=useState(true);const [query,setQuery]=useState(0);
  const retryKeys=useRef<Record<string,string>>({});
  const settings=useExportDraft(exportSettingsRoute(project,collection));
  const {options,overrides}=settings.draft;
  const uniform=settings.draft.settings_source==="uniform";
  const [outputSettings,setOutputSettings]=useState<Record<string,{options:ExportOptions;loaded:boolean;error:string;route:string}>>({});
  const recordSettings=useCallback((id:string,value:{options:ExportOptions;loaded:boolean;error:string;route:string})=>setOutputSettings(previous=>{
    const old=previous[id];
    if(old?.options===value.options&&old.loaded===value.loaded&&old.error===value.error&&old.route===value.route)return previous;
    return {...previous,[id]:value};
  }),[]);
  const chosen=outputs.filter(output=>selected.includes(output.output_id));
  function ready(output:Output){const entry=outputSettings[output.output_id];return entry?.route===exportSettingsRoute(project,collection,output.output_id)&&entry.loaded&&!entry.error;}
  function resolved(output:Output){return uniform?effectiveOutputOptions(settings.draft,output.output_id):outputSettings[output.output_id].options;}
  const outputsBlocked=chosen.some(output=>!ready(output));
  const settingsBlocked=!settings.loaded||!!settings.loadError;
  function setOverrides(next:Record<string,GeometryOptions>){settings.change({...settings.draft,overrides:next});}
  const active=Object.values(tasks).some(task=>task.status==="pending"||task.status==="running");
  const resultEntries=outputs.flatMap(output=>tasks[output.output_id]?[{outputId:output.output_id,taskId:tasks[output.output_id].task_id}]:[]);
  const requestSettings=JSON.stringify({selected,options,overrides,uniform,outputs:outputs.map(output=>({id:output.output_id,revision:output.revision,options:outputSettings[output.output_id]?.options}))});
  useEffect(()=>{key.current=undefined;retryKeys.current={};},[requestSettings]);
  useEffect(()=>{const controller=new AbortController();setRecovering(true);Promise.all(outputs.map(async output=>[output.output_id,await recoverOutputExport(project,collection,output.output_id,controller.signal)] as const)).then(rows=>{if(!controller.signal.aborted)setTasks(Object.fromEntries(rows.filter((row):row is readonly [string,OutputExportTask]=>row[1]!==null)));}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"恢复导出失败");}).finally(()=>{if(!controller.signal.aborted)setRecovering(false);});return()=>controller.abort();},[project,collection,outputs,query]);
  useEffect(()=>{if(!active)return;const controller=new AbortController();const timer=setTimeout(()=>{Promise.all(Object.entries(tasks).filter(([,task])=>task.status==="pending"||task.status==="running").map(async([id,task])=>[id,await readOutputExport(project,task.task_id,controller.signal)] as const)).then(rows=>{if(!controller.signal.aborted)setTasks(previous=>({...previous,...Object.fromEntries(rows)}));}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"读取导出失败");});},1000);return()=>{controller.abort();clearTimeout(timer);};},[tasks,active,project]);
  async function submit(output?:Output){if(lock.current||active||disabled||templateApplying||recovering||settingsBlocked||outputsBlocked||(output&&!ready(output)))return;lock.current=true;setSending(true);setError("");try{
    if(output){retryKeys.current[output.output_id]??=crypto.randomUUID();const task=await startOutputExport(project,collection,output.output_id,output.revision,resolved(output),retryKeys.current[output.output_id]);delete retryKeys.current[output.output_id];setTasks(previous=>({...previous,[output.output_id]:task}));}
    else {key.current??=crypto.randomUUID();const rows=await startOutputExportBatch(project,collection,chosen,options,key.current,{},Object.fromEntries(chosen.map(output=>[output.output_id,resolved(output)])));setTasks(previous=>({...previous,...Object.fromEntries(chosen.map((output,index)=>[output.output_id,rows[index]]))}));key.current=undefined;onSubmitted?.(chosen.map((output,index)=>({outputId:output.output_id,taskId:rows[index].task_id})));}
  }catch(reason){setError(reason instanceof Error?reason.message:"提交导出失败");}finally{lock.current=false;setSending(false);}}
  return <section aria-label="批量导出"><ExportSections cover={<BatchCoverTemplates project={project} collection={collection} outputs={outputs} selected={selected} disabled={disabled||active||sending||recovering} onBusy={setTemplateApplying}/> }><h2>批量画面设置</h2>
    <fieldset className="batch-settings-source" disabled={active||sending||settingsBlocked}><legend>本批次使用的设置</legend>
      <label><input type="radio" name={`batch-settings-${project}-${collection}`} checked={!uniform} onChange={()=>settings.change({...settings.draft,settings_source:"output"})}/>沿用各作品设置</label>
      <label><input type="radio" name={`batch-settings-${project}-${collection}`} checked={uniform} onChange={()=>settings.change({...settings.draft,settings_source:"uniform"})}/>统一使用批量设置／预设</label>
    </fieldset>
    <p className="helper-text">统一设置仅作用于本批次，不修改各作品的编辑设置。字幕文字、字号和位置沿用各作品已保存的版本。</p>
    {uniform&&<><OutputSettingsControls draft={settings.draft} onChange={settings.change} disabled={active||sending||settingsBlocked} label="批量" batch/>
    <details><summary>逐条画幅覆盖</summary>{outputs.filter(output=>selected.includes(output.output_id)).map(output=><div key={output.output_id}><label><input type="checkbox" disabled={active||sending||settingsBlocked} checked={!!overrides[output.output_id]} onChange={event=>setOverrides((()=>{const next={...overrides};if(event.target.checked)next[output.output_id]={aspect_ratio:options.aspect_ratio??"original",resolution:options.resolution??1080,fit:options.fit??"pad",crop_left:options.crop_left,crop_right:options.crop_right,crop_top:options.crop_top,crop_bottom:options.crop_bottom};else delete next[output.output_id];return next;})())} />单独设置 {output.title}</label>{overrides[output.output_id]&&<GeometrySettings label={output.title} value={overrides[output.output_id]} disabled={active||sending||settingsBlocked} onChange={geometry=>setOverrides({...overrides,[output.output_id]:geometry})} />}</div>)}</details>
    <button type="button" disabled={active||sending||settingsBlocked||Object.keys(overrides).length===0} onClick={()=>setOverrides({})}>清除全部逐条覆盖</button>
    {Object.keys(overrides).length>0&&<p className="helper-text">已开启逐条覆盖的作品优先使用各自画幅，统一设置和预设不会覆盖它们。</p>}
    </>}
    <h3>本批次作品与实际设置</h3>{chosen.length===0&&<p>先在左侧选择加入批量的作品。</p>}
    {outputs.map(output=><BatchSettingsRow key={output.output_id} project={project} collection={collection} output={output} selected={selected.includes(output.output_id)} uniformOptions={uniform?effectiveOutputOptions(settings.draft,output.output_id):undefined} onReady={recordSettings} onPreview={onPreview} disabled={disabled||active||sending||recovering||settingsBlocked}/>)}
    </ExportSections>
    <ExportDraftStatus state={settings}/>
    <button disabled={disabled||recovering||sending||active||templateApplying||settingsBlocked||outputsBlocked||selected.length===0} onClick={()=>void submit()}>导出已选作品</button><p className="helper-text">逐条导出，独立保存 · 刷新恢复进度</p><details><summary>导出说明</summary><p className="helper-text">导出不调用 AI。批次开始后，作品选择的变更仅用于下次导出。</p></details>
    {resultEntries.length>0&&onSubmitted&&<button onClick={()=>onSubmitted(resultEntries)}>查看全部导出结果</button>}
    {error&&<p role="alert">{error}<button onClick={()=>{setError("");setQuery(previous=>previous+1);}}>恢复状态查询</button></p>}
    <ul>{outputs.filter(output=>tasks[output.output_id]).map(output=>{const task=tasks[output.output_id];return <li key={output.output_id}>{output.title}：{task.status}{task.error&&` · ${task.error}`}{task.status==="succeeded"&&task.result&&<><a href={task.result.media_url} download>下载 {output.title}</a> · <a href={task.result.subtitle_url} download>字幕 {output.title}</a></>}{(task.status==="failed"||task.status==="cancelled")&&<button disabled={active||sending||disabled||templateApplying||settingsBlocked||!ready(output)} onClick={()=>void submit(output)}>重试 {output.title}</button>}</li>;})}</ul>
  </section>;
}

function BatchSettingsRow({project,collection,output,selected,uniformOptions,onReady,onPreview,disabled}:{project:string;collection:string;output:Output;selected:boolean;uniformOptions?:ExportOptions;onReady:(id:string,value:{options:ExportOptions;loaded:boolean;error:string;route:string})=>void;onPreview?:(id:string)=>void;disabled:boolean}) {
  const route=exportSettingsRoute(project,collection,output.output_id);
  const state=useExportDraft(route);
  useEffect(()=>{onReady(output.output_id,{options:state.draft.options,loaded:state.loaded,error:state.loadError,route});},[route,output.output_id,state.draft.options,state.loaded,state.loadError,onReady]);
  if(!selected)return null;
  const actual=uniformOptions??state.draft.options;
  const changed=uniformOptions&&JSON.stringify(actual)!==JSON.stringify(state.draft.options);
  return <article className="batch-settings-row" aria-label={`批量配置 ${output.title}`}><h4>{output.title} · v{output.revision}</h4>
    {state.loaded?<><OutputSettingsSummary options={actual}/><p className="helper-text">{uniformOptions?changed?"统一配置：与作品设置不同":"统一配置：与作品设置相同":"沿用作品设置"}</p></>:<p role="status">正在读取作品设置…</p>}
    {state.loadError&&<p role="alert">{state.loadError}<button onClick={state.retryLoad}>重试读取 {output.title} 设置</button></p>}
    {onPreview&&<button type="button" aria-label={`预览 ${output.title} 的批量效果`} disabled={disabled||!state.loaded||!!state.loadError} onClick={()=>onPreview(output.output_id)}>预览此作品的批量效果</button>}
  </article>;
}
