import { useEffect, useRef, useState } from "react";
import { getHighlights, editOutputItem, reorderOutput, getOutputVersions, type HighlightResult, type HighlightClip } from "./api";
import { OutputPreview } from "./OutputPreview";
import { OutputItemEditor } from "./OutputItemEditor";
import { OutputOrderControls } from "./OutputOrderControls";

export function OutputWorkspace({project, collection, output}: {project: string; collection: string; output: string}) {
  const [result, setResult] = useState<HighlightResult | null>(null); const [error, setError] = useState("");
  const [busy, setBusy] = useState(false); const lock = useRef(false);
  const [jumpTo, setJumpTo] = useState<{ms:number;sequence:number}>();
  const [versions,setVersions]=useState<{revision:number;duration_ms:number;clips:HighlightClip[]}[]>([]);
  const [historyError,setHistoryError]=useState("");
  const [viewVersion,setViewVersion]=useState<number|undefined>();
  async function orderSave(order:string[],roles:Record<string,string>) {if(lock.current) throw new Error("正在保存"); lock.current=true;setBusy(true);try {setResult(await reorderOutput(project,collection,output,order,roles));setViewVersion(undefined);setVersions([]);}finally {lock.current=false;setBusy(false);}}
  async function save(instance: string, changes: {deleted?: boolean; display_text?: string}) {
    if (lock.current) throw new Error("请等待当前保存完成");
    lock.current = true; setBusy(true);
    try {setResult(await editOutputItem(project, collection, output, instance, changes));setViewVersion(undefined);setVersions([]);}
    finally {lock.current = false; setBusy(false);}
  }
  useEffect(() => {const controller = new AbortController(); getHighlights(project, collection, controller.signal).then(value => {if (!controller.signal.aborted) setResult(value);}).catch((reason: unknown) => {if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "读取作品失败");}); return () => controller.abort();}, [project, collection]);
  if (error) return <p role="alert">{error}</p>;
  if (!result) return <p role="status">正在读取作品…</p>;
  const plan = result.outputs.find(plan => plan.output_id === output);
  if (!plan) return <p role="alert">作品不存在</p>;
  const historical = viewVersion !== undefined && viewVersion !== plan.revision;
  const visibleClips = versions.find(version => version.revision === viewVersion)?.clips ?? plan.clips;
  return <section><h1>{plan.title}</h1><p>{plan.reason} · 当前版本 {plan.revision} · {(plan.duration_ms/1000).toFixed(2)} 秒</p><p>文字更正只影响显示字幕，不改原话和源时间码。删除后可恢复；至少保留一段正文。导出设置将在下一闭环接通。</p><OutputOrderControls clips={visibleClips} busy={busy || historical} save={orderSave} /><button disabled={busy} onClick={()=>{setHistoryError("");void getOutputVersions(project,collection,output).then(setVersions).catch(reason=>setHistoryError(reason instanceof Error?reason.message:"读取版本失败"));}}>查看版本</button>{historyError&&<p role="alert">{historyError}</p>}{versions.length>0&&<label>预览版本<select value={viewVersion??plan.revision} onChange={event=>setViewVersion(Number(event.target.value))}>{versions.map(version=><option key={version.revision} value={version.revision}>版本 {version.revision}</option>)}</select></label>}<p>历史版本只读；早于开始记录的版本无法找回。</p><div className="output-edit-grid"><ol className="segments">{visibleClips.map(clip => <OutputItemEditor key={`${viewVersion ?? plan.revision}:${clip.instance_id}`} clip={clip} busy={busy || historical} onSave={changes => save(clip.instance_id, changes)} onJump={() => setJumpTo(previous => ({ms:clip.start_ms,sequence:(previous?.sequence ?? 0)+1}))} />)}</ol><OutputPreview key={`${collection}:${output}:${viewVersion??plan.revision}`} title={plan.title} clips={visibleClips} jumpTo={jumpTo} mediaUrl={`/api/projects/${encodeURIComponent(project)}/media/source/${encodeURIComponent(result.asset_id)}`} /></div></section>;
}
