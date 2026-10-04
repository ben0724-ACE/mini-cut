import {useEffect,useRef,useState} from "react";
import {getHighlights,listAssets,recoverHighlights,readHighlightTask,saveHighlightSelection,startOutputExportBatch,uploadAsset,type AssetDetail,type HighlightResult,type HighlightOutput} from "./api";
import {exportSettingsRoute,getExportDraft,type ExportOptions} from "./exportSettingsApi";
import {navigateToExportResults} from "./exportNavigation";
import {QuickPreview} from "./QuickPreview";
import {WorkflowManager} from "./WorkflowManager";
import {GenerationDetails} from "./GenerationDetails";
import {WorkspaceDialog} from "./WorkspaceDialog";
import {latestWorkflowRun,listWorkflows,startWorkflowRun,workflowAction,workflowsChanged,type Workflow,type WorkflowRun} from "./workflowApi";

const phaseLabels:Record<string,string>={pending:"等待执行",transcribe:"转录素材",highlights:"AI 选材与字幕",configure:"应用成片配置",export:"导出作品",completed:"已完成"};
function savedWorkflow(project:string){try{return localStorage.getItem(`minicut:workflow:${project}`)??localStorage.getItem("minicut:workflow")??"";}catch{return "";}}
function rememberWorkflow(project:string,id:string){try{localStorage.setItem(`minicut:workflow:${project}`,id);localStorage.setItem("minicut:workflow",id);}catch{/* Selection remains available for this session. */}}
export function MinimalWorkspace({project,onRefine}:{project:string;onRefine:(collection:string,output:string)=>void}){
  const [workflows,setWorkflows]=useState<Workflow[]>([]);const [workflowId,setWorkflowId]=useState(()=>savedWorkflow(project));
  const [assets,setAssets]=useState<AssetDetail[]>([]);const [assetId,setAssetId]=useState("");const [file,setFile]=useState<File|null>(null);const input=useRef<HTMLInputElement>(null);
  const [run,setRun]=useState<WorkflowRun|null>(null);const [result,setResult]=useState<HighlightResult|null>(null);const [selected,setSelected]=useState<string[]>([]);const [focused,setFocused]=useState("");
  const [detailsOpen,setDetailsOpen]=useState(false);
  const [loaded,setLoaded]=useState(false);const [busy,setBusy]=useState(false);const [error,setError]=useState("");const [retry,setRetry]=useState(0);const [libraryRetry,setLibraryRetry]=useState(0);const [status,setStatus]=useState("");
  const lock=useRef(false);const runKey=useRef<string|null>(null);const uploaded=useRef<string|null>(null);const exportKey=useRef<string|null>(null);
  const active=run?.status==="pending"||run?.status==="running";
  const workflow=workflows.find(w=>w.workflow_id===workflowId);const output=result?.outputs.find(o=>o.output_id===focused)??result?.outputs[0];
  function applyResult(value:HighlightResult|null){setResult(value);setSelected(value?.selected_output_ids??[]);}
  useEffect(()=>{const refresh=()=>setLibraryRetry(value=>value+1);window.addEventListener(workflowsChanged,refresh);return()=>window.removeEventListener(workflowsChanged,refresh);},[]);
  useEffect(()=>{const controller=new AbortController();listWorkflows(controller.signal).then(value=>{if(!controller.signal.aborted){setWorkflows(value);setWorkflowId(current=>value.some(w=>w.workflow_id===current)?current:value[0]?.workflow_id??"");}}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"无法读取工作流");});return()=>controller.abort();},[libraryRetry,retry]);
  useEffect(()=>{const controller=new AbortController();setLoaded(false);setError("");Promise.all([listAssets(project,controller.signal),latestWorkflowRun(project,controller.signal)]).then(async([items,latest])=>{
    if(controller.signal.aborted)return;setAssets(items);setRun(latest);const asset=latest?.asset_id??items[0]?.asset_id??"";setAssetId(asset);
    const generation=latest?.result??(asset?(await recoverHighlights(project,asset,controller.signal))?.result:null);
    const current=generation?await getHighlights(project,generation.collection_id,controller.signal):null;
    if(!controller.signal.aborted){applyResult(current);setLoaded(true);}
  }).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"无法恢复工作区");});return()=>controller.abort();},[project,retry]);
  useEffect(()=>{if(!active||!run)return;const controller=new AbortController();const timer=setTimeout(async()=>{try{
    const latest=await latestWorkflowRun(project,controller.signal);if(controller.signal.aborted)return;setRun(latest);
    if(latest?.result&&(latest.result.collection_id!==result?.collection_id||latest.status!==run.status||latest.phase!==run.phase)){const current=await getHighlights(project,latest.result.collection_id,controller.signal);if(!controller.signal.aborted)applyResult(current);}
    if(latest?.child_task_ids.length&&latest.phase==="transcribe"){const task=await readHighlightTask(project,latest.child_task_ids[0],controller.signal);if(!controller.signal.aborted)setStatus(task.progress?.total?`已完成 ${task.progress.completed??0} / ${task.progress.total} 个转录块`:"");}
  }catch(reason){if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"查询失败");}},1500);return()=>{clearTimeout(timer);controller.abort();};},[project,run,active]);
  async function action(operation:()=>Promise<void>){if(lock.current)return;lock.current=true;setBusy(true);setError("");try{await operation();}catch(reason){setError(reason instanceof Error?reason.message:"操作失败");}finally{lock.current=false;setBusy(false);setStatus("");}}
  async function start(){if(!workflow||active)return;let asset=assetId;
    if(file&&!uploaded.current){setStatus("正在导入视频…");const imported=await uploadAsset(project,file);uploaded.current=imported.asset_id;asset=imported.asset_id;setAssetId(asset);setAssets(await listAssets(project));}
    else if(uploaded.current)asset=uploaded.current;
    if(!asset)throw new Error("请先选择视频");runKey.current??=crypto.randomUUID();
    rememberWorkflow(project,workflow.workflow_id);const started=await startWorkflowRun(project,asset,workflow.workflow_id,runKey.current);setRun(started);applyResult(started.result);setFile(null);uploaded.current=null;runKey.current=null;
  }
  async function selectAsset(id:string){setAssetId(id);setFile(null);uploaded.current=null;runKey.current=null;const task=await recoverHighlights(project,id);applyResult(task?.result?await getHighlights(project,task.result.collection_id):null);setFocused("");}
  async function toggleSelected(id:string,checked:boolean){if(!result)return;const ids=checked?[...selected,id]:selected.filter(value=>value!==id);const current=await saveHighlightSelection(project,result.collection_id,ids);applyResult(current);exportKey.current=null;}
  async function exportSelected(){if(!result||!selected.length)return;
    const current=await getHighlights(project,result.collection_id);const outputs=current.outputs.filter(o=>selected.includes(o.output_id));
    if(!outputs.length)throw new Error("已选作品发生变化，请重新选择作品");
    const options=await Promise.all(outputs.map(async o=>[o.output_id,(await getExportDraft(exportSettingsRoute(project,current.collection_id,o.output_id))).draft.options] as const));
    exportKey.current??=crypto.randomUUID();const outputOptions:Record<string,ExportOptions>=Object.fromEntries(options);
    const tasks=await startOutputExportBatch(project,current.collection_id,outputs.map(o=>({output_id:o.output_id,revision:o.revision})),options[0][1],exportKey.current,{},outputOptions);
    navigateToExportResults(project,current.collection_id,tasks.map((task,index)=>({outputId:outputs[index].output_id,taskId:task.task_id})));
  }
  const blocked=busy||active||!loaded;
  return <section className="minimal-workspace" aria-label="极简工作台">
    <div className="minimal-launch">
      <div className="minimal-source-field"><span className="minimal-field-label">视频</span><div className="minimal-field-controls">
        {file?<span className="minimal-file-name" title={file.name}>{file.name}</span>:assets.length?<select aria-label="极简模式素材" value={assetId} disabled={blocked} onChange={event=>void action(()=>selectAsset(event.target.value))}>{assets.map(asset=><option key={asset.asset_id} value={asset.asset_id}>{asset.name}</option>)}</select>:<span className="minimal-file-name muted">未选择视频</span>}
        <input ref={input} hidden type="file" accept=".mp4,.mov,.mkv,.avi,.flv,.f4v,.webm,.ogg,.wav,.mp3,.flac,.m4a" aria-label="上传视频" disabled={blocked} onChange={event=>{setFile(event.target.files?.[0]??null);uploaded.current=null;runKey.current=null;}}/>
        <button type="button" disabled={blocked} onClick={()=>input.current?.click()}>选择本地视频</button>
      </div></div>
      <div className="minimal-workflow-field"><label className="minimal-field-label" htmlFor="minimal-workflow">工作流</label><div className="minimal-field-controls">
        <select id="minimal-workflow" aria-label="工作流" value={workflowId} disabled={blocked} onChange={event=>{setWorkflowId(event.target.value);rememberWorkflow(project,event.target.value);runKey.current=null;}}><option value="">请选择工作流</option>{workflows.map(w=><option key={w.workflow_id} value={w.workflow_id}>{w.name}</option>)}</select>
        <WorkflowManager project={project} asset={assetId||undefined} triggerLabel="管理" onSaved={saved=>{setWorkflowId(saved.workflow_id);rememberWorkflow(project,saved.workflow_id);runKey.current=null;}}/>
      </div></div>
      <button className="primary-button minimal-run" disabled={blocked||!workflow||(!file&&!assetId)} onClick={()=>void action(start)}>{busy?status||"正在提交…":active?"正在执行…":workflow?.auto_export?"一键生成并导出":"一键生成"}</button>
      <div className="minimal-launch-meta">
        <span>{workflow?`${workflow.transcription.language==="en"?"英文":"中文"} · ${workflow.generation.preset==="clean_speech"?1:workflow.generation.count} 条 · ${workflow.generation.limit_duration&&workflow.generation.preset!=="clean_speech"?`${workflow.generation.min_seconds}–${workflow.generation.max_seconds} 秒`:"不限时"} · ${workflow.export_options.aspect_ratio==="original"?"原始比例":workflow.export_options.aspect_ratio} · ${workflow.auto_export?"自动导出":"生成后审阅"}`:loaded?"点击“管理”保存常用工作流，之后直接运行。":"正在恢复工作区…"}</span>
        <span title="视频在本地处理，转录文本会发送至配置的 AI 服务。">AI 处理可能产生费用</span>
      </div>
    </div>
    {error&&<p role="alert" className="minimal-notice">{error}<button type="button" disabled={busy} onClick={()=>{setError("");setRetry(value=>value+1);}}>重新读取状态</button></p>}
    {run&&<div className="minimal-progress" role="status"><span className="minimal-progress-text"><strong>{run.workflow_name}</strong> · {run.status==="succeeded"?"已完成":run.status==="failed"?"执行失败":run.status==="cancelled"?"已取消":phaseLabels[run.phase]??run.phase}{active&&status?` · ${status}`:""}</span>
      {active&&<button type="button" disabled={busy||run.cancel_requested} onClick={()=>void action(async()=>setRun(await workflowAction(project,run.task_id,"cancel")))}>{run.cancel_requested?"正在取消…":"取消工作流"}</button>}
      {(run.status==="failed"||run.status==="cancelled")&&<button type="button" disabled={busy} onClick={()=>void action(async()=>setRun(await workflowAction(project,run.task_id,"resume")))}>继续工作流</button>}
      {!!run.exports?.length&&run.result&&<button type="button" onClick={()=>navigateToExportResults(project,run.result!.collection_id,run.exports)}>查看导出结果</button>}
    </div>}
    {run?.error&&<p role="alert" className="minimal-notice">{run.error}</p>}
    {result?<section aria-label="极简模式结果" className="minimal-results">
      <div className="minimal-results-heading"><h2>候选作品 <span className="muted">{result.outputs.length} 条</span></h2><div className="minimal-results-actions"><button type="button" onClick={()=>setDetailsOpen(true)}>生成详情</button><button type="button" disabled={blocked||!selected.length} onClick={()=>void action(exportSelected)}>导出已选作品（{selected.length}）</button></div></div>
      {result.outputs.length?<div className="minimal-result-layout"><div className="minimal-candidates" aria-label="候选列表">{result.outputs.map(o=><article className={`minimal-candidate ${output?.output_id===o.output_id?"is-current":""}`} key={o.output_id}>
        <button className="candidate-title" type="button" title={o.title} aria-pressed={output?.output_id===o.output_id} onClick={()=>setFocused(o.output_id)}>{o.title}</button><p className="muted">{(o.duration_ms/1000).toFixed(1)} 秒</p>
        <div className="minimal-candidate-actions"><label className="checkbox-field"><input type="checkbox" aria-label={`选择${o.title}`} disabled={blocked} checked={selected.includes(o.output_id)} onChange={event=>void action(()=>toggleSelected(o.output_id,event.target.checked))}/>选择导出</label><button type="button" disabled={active} onClick={()=>onRefine(result.collection_id,o.output_id)}>精修</button></div>
      </article>)}</div>{output&&<MinimalPreview key={`${result.collection_id}:${output.output_id}`} project={project} result={result} output={output}/>}</div>:<div className="minimal-empty"><p>没有符合要求的候选，请在完整模式调整选材要求。</p></div>}
    </section>:<div className="minimal-empty"><h2>准备好下一条作品</h2><p>{loaded?"选择视频和工作流，点击一键生成。":"正在恢复素材与作品…"}</p></div>}
    <WorkspaceDialog open={detailsOpen} title="生成详情" onClose={()=>setDetailsOpen(false)}>{result&&<GenerationDetails expanded assetName={assets.find(a=>a.asset_id===result.asset_id)?.name??"当前素材"} result={result}/>}</WorkspaceDialog>
  </section>;
}
function MinimalPreview({project,result,output}:{project:string;result:HighlightResult;output:HighlightOutput}){
  return <section className="minimal-preview" aria-label="作品试听"><h3 title={output.title}>{output.title}</h3><div className="minimal-media"><QuickPreview compact sourceUrl={`/api/projects/${encodeURIComponent(project)}/media/source/${encodeURIComponent(result.asset_id)}`} title={output.title} clips={output.clips} onDuration={()=>{}}/></div><p className="helper-text minimal-preview-hint">源视频试听 · 成片字幕与转场以导出为准</p>{output.workflow==="speech_cleanup"?<p>此流程不生成文案</p>:<details className="minimal-reason"><summary>选材理由</summary><p className="helper-text">{output.reason}</p></details>}</section>;
}
