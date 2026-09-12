import { useEffect, useState } from "react";
import { getHighlights, type HighlightResult } from "./api";
import { OutputPreview } from "./OutputPreview";

export function OutputWorkspace({project, collection, output}: {project: string; collection: string; output: string}) {
  const [result, setResult] = useState<HighlightResult | null>(null); const [error, setError] = useState("");
  useEffect(() => {const controller = new AbortController(); getHighlights(project, collection, controller.signal).then(value => {if (!controller.signal.aborted) setResult(value);}).catch((reason: unknown) => {if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "读取作品失败");}); return () => controller.abort();}, [project, collection]);
  if (error) return <p role="alert">{error}</p>;
  if (!result) return <p role="status">正在读取作品…</p>;
  const plan = result.outputs.find(plan => plan.output_id === output);
  if (!plan) return <p role="alert">作品不存在</p>;
  return <section><h1>{plan.title}</h1><p>{plan.reason} · 版本 {plan.revision}</p><p>已进入独立作品工作区；修改、重排和导出设置将在 M6 接通，目前只读。</p><OutputPreview key={`${collection}:${output}`} title={plan.title} clips={plan.clips} mediaUrl={`/api/projects/${encodeURIComponent(project)}/media/source/${encodeURIComponent(result.asset_id)}`} /><ol>{plan.clips.map(clip => <li key={clip.instance_id}>{clip.role === "hook" ? "原话钩子" : "正文"} · {(clip.start_ms/1000).toFixed(2)}–{(clip.end_ms/1000).toFixed(2)} 秒：{clip.text}</li>)}</ol></section>;
}
