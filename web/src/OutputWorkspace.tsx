import { useEffect, useRef, useState, type ReactNode } from "react";
import { getHighlights, editOutputItem, reorderOutput, getOutputVersions, type HighlightResult, type HighlightClip } from "./api";
import { OutputPreview } from "./OutputPreview";
import { OutputItemEditor } from "./OutputItemEditor";
import { OutputOrderControls } from "./OutputOrderControls";
import { OutputExport } from "./OutputExport";
import { Workbench } from "./Workbench";
interface Panels {preview:ReactNode;edit:ReactNode;exportPanel:ReactNode}
export function OutputWorkspace({project,collection,output,compose,onUpdated}:{project:string;collection:string;output:string;compose?:(panels:Panels)=>ReactNode;onUpdated?:(result:HighlightResult)=>void}) {
  const [result,setResult]=useState<HighlightResult|null>(null);const [error,setError]=useState("");const [busy,setBusy]=useState(false);const lock=useRef(false);
  const [jumpTo,setJumpTo]=useState<{ms:number;sequence:number}>();
  const [versions,setVersions]=useState<{revision:number;duration_ms:number;clips:HighlightClip[]}[]>([]);
  const [historyError,setHistoryError]=useState("");const [viewVersion,setViewVersion]=useState<number|undefined>();
  async function update(operation:()=>Promise<HighlightResult>){if(lock.current)throw new Error("请等待当前保存完成");lock.current=true;setBusy(true);try{const updated=await operation();setResult(updated);onUpdated?.(updated);setViewVersion(undefined);setVersions([]);}finally{lock.current=false;setBusy(false);}}
  useEffect(()=>{const controller=new AbortController();getHighlights(project,collection,controller.signal).then(value=>{if(!controller.signal.aborted)setResult(value);}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"读取作品失败");});return()=>controller.abort();},[project,collection]);
  if(error)return <p role="alert">{error}</p>;if(!result)return <p role="status">正在读取作品…</p>;
  const plan=result.outputs.find(plan=>plan.output_id===output);if(!plan)return <p role="alert">作品不存在</p>;
  const historical=viewVersion!==undefined&&viewVersion!==plan.revision;
  const visibleClips=versions.find(version=>version.revision===viewVersion)?.clips??plan.clips;
  const preview=<><h1 className="preview-title">{plan.title}</h1><p className="muted">v{viewVersion??plan.revision} · {(plan.duration_ms/1000).toFixed(1)} 秒</p><OutputPreview key={`${collection}:${output}:${viewVersion??plan.revision}`} title={plan.title} clips={visibleClips} jumpTo={jumpTo} mediaUrl={`/api/projects/${encodeURIComponent(project)}/media/source/${encodeURIComponent(result.asset_id)}`} /></>;
  const edit=<><OutputOrderControls clips={visibleClips} busy={busy||historical} save={(order,roles)=>update(()=>reorderOutput(project,collection,output,order,roles))} /><details><summary>版本记录</summary><button disabled={busy} onClick={()=>{setHistoryError("");void getOutputVersions(project,collection,output).then(setVersions).catch(reason=>setHistoryError(reason instanceof Error?reason.message:"读取版本失败"));}}>查看版本</button>{historyError&&<p role="alert">{historyError}</p>}{versions.length>0&&<label>预览版本<select value={viewVersion??plan.revision} onChange={event=>setViewVersion(Number(event.target.value))}>{versions.map(version=><option key={version.revision} value={version.revision}>版本 {version.revision}</option>)}</select></label>}<p className="muted">历史只读，记录启用前的版本不可找回。</p></details><ol className="segments">{visibleClips.map(clip=><OutputItemEditor key={`${viewVersion??plan.revision}:${clip.instance_id}`} clip={clip} busy={busy||historical} onSave={changes=>update(()=>editOutputItem(project,collection,output,clip.instance_id,changes))} onJump={()=>setJumpTo(previous=>({ms:clip.start_ms,sequence:(previous?.sequence??0)+1}))} />)}</ol><details><summary>编辑说明</summary><p>文字修改只影响字幕，不改变原话和时间码。删除可恢复，至少保留一段正文。</p></details></>;
  const exportPanel=historical?<p>切回当前版本后导出</p>:<OutputExport key={`${collection}:${output}:${plan.revision}`} project={project} collection={collection} output={output} revision={plan.revision} />;
  return compose?compose({preview,edit,exportPanel}):<Workbench sidebar={<><h2>当前作品</h2><p>{plan.title}</p><details><summary>选材理由</summary><p>{plan.reason}</p></details><a href={`?project=${encodeURIComponent(project)}`}>返回候选列表</a></>} preview={preview} generate={<p>返回候选列表以生成新作品</p>} edit={edit} exportPanel={exportPanel} />;
}
