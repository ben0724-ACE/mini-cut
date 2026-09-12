import { useEffect, useRef, useState } from "react";
import { getHighlights, editOutputItem, type HighlightResult } from "./api";
import { OutputPreview } from "./OutputPreview";
import { OutputItemEditor } from "./OutputItemEditor";

export function OutputWorkspace({project, collection, output}: {project: string; collection: string; output: string}) {
  const [result, setResult] = useState<HighlightResult | null>(null); const [error, setError] = useState("");
  const [busy, setBusy] = useState(false); const lock = useRef(false);
  const [jumpTo, setJumpTo] = useState<{ms:number;sequence:number}>();
  async function save(instance: string, changes: {deleted?: boolean; display_text?: string}) {
    if (lock.current) throw new Error("请等待当前保存完成");
    lock.current = true; setBusy(true);
    try {setResult(await editOutputItem(project, collection, output, instance, changes));}
    finally {lock.current = false; setBusy(false);}
  }
  useEffect(() => {const controller = new AbortController(); getHighlights(project, collection, controller.signal).then(value => {if (!controller.signal.aborted) setResult(value);}).catch((reason: unknown) => {if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "读取作品失败");}); return () => controller.abort();}, [project, collection]);
  if (error) return <p role="alert">{error}</p>;
  if (!result) return <p role="status">正在读取作品…</p>;
  const plan = result.outputs.find(plan => plan.output_id === output);
  if (!plan) return <p role="alert">作品不存在</p>;
  return <section><h1>{plan.title}</h1><p>{plan.reason} · 版本 {plan.revision} · {(plan.duration_ms/1000).toFixed(2)} 秒</p><p>文字更正只影响显示字幕，不改原话和源时间码。删除后可恢复；至少保留一段正文。重排与导出设置将在后续闭环接通。</p><div className="output-edit-grid"><ol className="segments">{plan.clips.map(clip => <OutputItemEditor key={clip.instance_id} clip={clip} busy={busy} onSave={changes => save(clip.instance_id, changes)} onJump={() => setJumpTo(previous => ({ms:clip.start_ms,sequence:(previous?.sequence ?? 0)+1}))} />)}</ol><OutputPreview key={`${collection}:${output}`} title={plan.title} clips={plan.clips} jumpTo={jumpTo} mediaUrl={`/api/projects/${encodeURIComponent(project)}/media/source/${encodeURIComponent(result.asset_id)}`} /></div></section>;
}
