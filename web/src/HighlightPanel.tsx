import { useEffect, useRef, useState, type ReactNode } from "react";
import { recoverHighlights, readHighlightTask, resumeTask, cancelOutputExport, startHighlights, getHighlights, saveHighlightSelection, type AssetDetail, type HighlightTask } from "./api";
import { HighlightForm, type HighlightBrief } from "./HighlightForm";
import { ModelUsage } from "./ModelUsage";
import { BatchExport } from "./BatchExport";
import { Workbench, type WorkbenchTab } from "./Workbench";
import { navigateWithDraft } from "./draftNavigation";
import { OutputWorkspace } from "./OutputWorkspace";

export function HighlightPanel({project, asset, recover = recoverHighlights, sidebar}: {project: string; asset: AssetDetail; recover?: typeof recoverHighlights;sidebar?:ReactNode}) {
  const [dirty,setDirty]=useState(false);
  const [task, setTask] = useState<HighlightTask | null>(null);
  const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false); const [retry, setRetry] = useState(0);
  const lock = useRef(false); const identity = useRef<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]); const [saving, setSaving] = useState(false); const [selectionError, setSelectionError] = useState(""); const [onlySelected, setOnlySelected] = useState(false);
  const [selectionLoading, setSelectionLoading] = useState(true);
  const collection = task?.result?.collection_id ?? "";
  const [focused,setFocused]=useState("");
  const [panel,setPanel]=useState<WorkbenchTab>("generate");
  useEffect(()=>{if(collection&&task?.status==="succeeded")setPanel(task.result?.outputs.length ? "edit" : "generate");},[collection,task?.status]);
  function focusOutput(output:string){navigateWithDraft(()=>{setFocused(output);setPanel("edit");});}
  useEffect(() => {
    if (task?.status !== "succeeded" || !collection) return;
    setSelectionLoading(true);
    const controller = new AbortController();
    getHighlights(project, collection, controller.signal).then(result => {if (!controller.signal.aborted) {setSelected(result.selected_output_ids ?? []); setSelectionLoading(false); if (result.outputs) setTask(previous => previous ? {...previous, result} : previous);}}).catch(() => {if (!controller.signal.aborted) setSelectionError("无法恢复作品选择，请刷新后重试。");});
    return () => controller.abort();
  }, [project, collection, task?.status]);
  async function select(output: string, checked: boolean) {
    if (!collection || saving || selectionLoading) return;
    setSaving(true); setSelectionError("");
    const updated = checked ? [...selected, output] : selected.filter(id => id !== output);
    try {const result = await saveHighlightSelection(project, collection, updated); setSelected(result.selected_output_ids ?? []);}
    catch (reason: unknown) {setSelectionError(reason instanceof Error ? reason.message : "选择保存失败");}
    finally {setSaving(false);}
  }
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
    if (!identity.current || task?.status === "succeeded" || task?.status === "failed" || task?.status === "cancelled") identity.current = crypto.randomUUID();
    try {setTask(await startHighlights(project, asset.asset_id, brief, identity.current));}
    catch (reason: unknown) {setError(reason instanceof Error ? reason.message : "生成提交失败");}
    finally {lock.current = false; setSubmitting(false);}
  }
  const result=task?.status==="succeeded"?task.result:null;
  const current=result?.outputs.find(output=>output.output_id===focused)??result?.outputs[0];
  const generation=<><HighlightForm ready={asset.has_transcript} busy={loading||submitting||active||!!error} onSubmit={brief=>navigateWithDraft(()=>void submit(brief))} />{error&&<p role="alert">{error}<button onClick={()=>{setError("");setLoading(true);setRetry(value=>value+1);}}>恢复查询</button></p>}{active&&<p role="status">{task.status==="pending"?"等待 AI 生成":"AI 正在生成"}</p>}{active&&<button onClick={()=>void cancelOutputExport(project,task.task_id).catch(reason=>setError(reason instanceof Error?reason.message:"取消失败"))}>取消生成</button>}{task?.status==="failed"&&<p role="alert">生成失败：{task.error}</p>}{(task?.status==="failed"||task?.status==="cancelled")&&task.resumable&&<button disabled={submitting} onClick={async()=>{setSubmitting(true);setError("");try{setTask(await resumeTask<HighlightTask>(project,task.task_id));}catch(reason){setError(reason instanceof Error?reason.message:"恢复失败");}finally{setSubmitting(false);}}}>恢复生成（复用已完成分析）</button>}{task?.status==="cancelled"&&<p role="status">生成已取消，已完成分析可恢复。</p>}{result?.model_requests&&<ModelUsage requests={result.model_requests} />}{result&&<details><summary>生成详情</summary><p>源素材：{asset.name}</p>{result.notes.map((note,index)=><p key={index}>{note}</p>)}</details>}</>;
  const shortlist=<>{sidebar}<h2>候选作品</h2>{result&&<><label><input type="checkbox" checked={onlySelected} onChange={event=>setOnlySelected(event.target.checked)} />只看已选作品</label><p className="muted">{result.outputs.length} 条候选 · 已选 {selected.length} 条{saving?" · 保存中":""}</p>{selectionError&&<p role="alert">{selectionError}</p>}<div className="candidate-list">{result.outputs.filter(output=>!onlySelected||selected.includes(output.output_id)).map(output=><article key={output.output_id} className={`candidate-row ${current?.output_id===output.output_id?"is-current":""}`}><button className="candidate-title" aria-pressed={current?.output_id===output.output_id} onClick={()=>focusOutput(output.output_id)}>{output.title}</button><p className="muted">{(output.duration_ms/1000).toFixed(1)} 秒 · v{output.revision}</p><label><input type="checkbox" aria-label={`选择${output.title}`} disabled={saving||selectionLoading} checked={selected.includes(output.output_id)} onChange={event=>void select(output.output_id,event.target.checked)} />加入批量</label><details><summary>选材理由</summary><p className="helper-text">{output.reason}</p></details></article>)}</div>{onlySelected&&selected.length===0&&<p>尚未选择作品</p>}{result.outputs.length===0&&<p>没有符合要求的候选，请调整要求。</p>}</>}{!result&&<p className="muted">生成后在此选择作品</p>}</>;
  const batch=result&&result.outputs.length>0?<BatchExport project={project} collection={collection} outputs={result.outputs} selected={selected} disabled={saving||selectionLoading||dirty} />:null;
  if(current) return <OutputWorkspace onDirty={setDirty} key={`${collection}:${current.output_id}`} project={project} collection={collection} output={current.output_id} compose={({preview,edit,exportPanel})=><Workbench tab={panel} onTabChange={setPanel} sidebar={shortlist} preview={preview} generate={generation} edit={edit} exportPanel={<>{exportPanel}<hr />{batch}</>} />} onUpdated={updated=>setTask(previous=>previous?{...previous,result:updated}:previous)} />;
  return <Workbench tab={panel} onTabChange={setPanel} sidebar={shortlist} preview={<div className="empty-preview">导入并转录素材，生成候选后预览</div>} generate={generation} edit={<p>先选择一个候选作品</p>} exportPanel={<p>尚无可导出作品</p>} />;
}
