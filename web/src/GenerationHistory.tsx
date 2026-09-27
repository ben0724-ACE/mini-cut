import { useEffect, useState } from "react";
import { getGenerationHistory, type GenerationHistoryEntry } from "./api";

const labels:Record<string,string> = {
  preset:"预设", preset_prompt:"预设提示词", instructions:"剪辑要求", count:"数量",
  min_ms:"最短时长", max_ms:"最长时长", hook_ms:"开场预告", max_source_overlap:"作品间素材重叠上限",
  body_mode:"正文模式", translation_language:"翻译语言", subtitle_mode:"字幕显示",
};
const presets:Record<string,string> = {podcast_highlights:"播客精选",knowledge_digest:"知识精华",opinion_first:"观点先行",clean_speech:"口播清理"};
const statuses:Record<string,string> = {pending:"等待生成",running:"生成中",succeeded:"已完成",failed:"失败",cancelled:"已取消"};
function display(key:string, value:unknown):string {
  if (key === "preset") return presets[String(value)] ?? String(value);
  if (key === "body_mode") return value === "continuous" ? "连续正文" : "精简拼接";
  if (key === "min_ms" || key === "max_ms") return value == null ? "不限制" : `${Number(value)/1000} 秒`;
  if (key === "hook_ms") return value == null ? "关闭" : `${Number(value)/1000} 秒`;
  if (key === "max_source_overlap") return `${Math.round(Number(value)*100)}%`;
  if (key === "translation_language") return value == null ? "关闭" : value === "zh" ? "中文" : "英文";
  if (key === "subtitle_mode") return value === "bilingual" ? "双语" : "仅译文";
  return String(value);
}
export function GenerationHistory({project,asset,refreshKey,disabled,onLoad}:{project:string;asset:string;refreshKey:string;disabled:boolean;onLoad:(entry:GenerationHistoryEntry)=>void}) {
  const [open, setOpen] = useState(false);
  const [allAssets, setAllAssets] = useState(false);
  const [entries, setEntries] = useState<GenerationHistoryEntry[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(()=>{
    if (!open) return;
    const controller = new AbortController();
    setLoading(true); setError("");
    getGenerationHistory(project, allAssets ? undefined : asset, controller.signal).then(value=>{
      if (controller.signal.aborted) return;
      setEntries(value); setSelected(previous=>value.some(entry=>entry.history_id===previous)?previous:value[0]?.history_id??""); setLoading(false);
    }).catch(reason=>{if (!controller.signal.aborted) {setError(reason instanceof Error?reason.message:"无法读取生成历史");setLoading(false);}});
    return ()=>controller.abort();
  }, [project, asset, allAssets, open, refreshKey, retry]);
  const entry = entries.find(item=>item.history_id===selected);
  return <details className="generation-history" onToggle={event=>setOpen(event.currentTarget.open)}>
    <summary>生成历史</summary>
    {open&&<>
      <p className="helper-text">查看当次提交的提示词和参数。载入只填写草稿，不会自动调用 AI。</p>
      <label>历史范围<select aria-label="历史范围" value={allAssets?"project":"asset"} onChange={event=>setAllAssets(event.target.value==="project")}><option value="asset">当前素材</option><option value="project">整个项目</option></select></label>
      {loading&&<p role="status">正在读取生成历史…</p>}
      {error&&<p role="alert">{error}<button type="button" onClick={()=>setRetry(value=>value+1)}>重试读取历史</button></p>}
      {!loading&&!error&&!entries.length&&<p>尚无生成历史</p>}
      {!loading&&!error&&entry&&<>
        <label>生成记录<select aria-label="生成记录" value={selected} onChange={event=>setSelected(event.target.value)}>{entries.map(item=><option key={item.history_id} value={item.history_id}>{item.created_at?new Date(item.created_at).toLocaleString():"时间未记录"} · {statuses[item.status]??item.status} · {item.asset_name??item.asset_id} · {item.history_id}</option>)}</select></label>
        <p className="helper-text">素材：{entry.asset_name??entry.asset_id} · {statuses[entry.status]??entry.status}</p>
        {entry.custom_preset_name&&<p className="helper-text">当次自定义预设：{entry.custom_preset_name}</p>}
        {entry.error&&<p>当次错误：{entry.error}</p>}
        <label>历史预设提示词<textarea aria-label="历史预设提示词" readOnly value={entry.brief.preset_prompt??"未记录，无法确认当时使用的预设提示词"} /></label>
        <label>历史剪辑要求<textarea aria-label="历史剪辑要求" readOnly value={entry.brief.instructions??"未记录"} /></label>
        <dl className="generation-history-parameters">{Object.entries(labels).filter(([key])=>key!=="preset_prompt"&&key!=="instructions").map(([key,label])=>{
          const value=entry.brief[key as keyof typeof entry.brief];
          return <div key={key}><dt>{label}</dt><dd>{entry.missing_fields.includes(key)||value===undefined?"未记录":display(key,value)}</dd></div>;
        })}</dl>
        {!!entry.missing_fields.length&&<p className="helper-text">旧记录缺少：{entry.missing_fields.map(field=>labels[field]??field).join("、")}。载入草稿时会用当前默认设置补齐，请核对。</p>}
        <button type="button" disabled={disabled||Object.keys(entry.brief).length===0} onClick={()=>onLoad(entry)}>载入为草稿</button>
      </>}
    </>}
  </details>;
}
