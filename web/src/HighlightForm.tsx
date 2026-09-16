import { useState } from "react";
import presetDefaults from "../../src/minicut/preset_prompts.json";

export interface HighlightBrief {preset: string; count: number; min_ms: number | null; max_ms: number | null; hook_ms: number | null; instructions: string; max_source_overlap: number; preset_prompt?:string; body_mode?:"continuous"|"compact"}
export function HighlightForm({ready, busy, onSubmit}: {ready: boolean; busy: boolean; onSubmit: (brief: HighlightBrief) => void}) {
  const [bodyMode,setBodyMode]=useState<"continuous"|"compact">("continuous");
  const [preset, setPreset] = useState("podcast_highlights");
  const [prompts, setPrompts] = useState<Record<string,string>>(presetDefaults);
  const [instructions, setInstructions] = useState("");
  const [count, setCount] = useState(3);
  const [min, setMin] = useState(60); const [max, setMax] = useState(90);
  const [hook, setHook] = useState(false); const [overlap, setOverlap] = useState(30);
  const [error, setError] = useState("");
  return <form className="transcription-controls" onSubmit={event => {
    event.preventDefault();
    if (!ready || busy) return;
    if (!Number.isInteger(count) || count < 1 || count > 10 || !Number.isFinite(min) || !Number.isFinite(max) || min <= 0 || max < min || overlap < 0 || overlap > 100 || !prompts[preset]?.trim()) {setError("请检查数量（1–10）与时长范围、重复比例"); return;}
    setError(""); onSubmit({body_mode:bodyMode,preset, preset_prompt:prompts[preset], instructions, count, min_ms: preset === "clean_speech" ? null : Math.round(min * 1000), max_ms: preset === "clean_speech" ? null : Math.round(max * 1000), hook_ms: hook ? 5000 : null, max_source_overlap: count === 1 ? 1 : overlap / 100});
  }}>
    <h2>AI 生成</h2><label>预设<select aria-label="预设" value={preset} disabled={busy} onChange={event => setPreset(event.target.value)}><option value="podcast_highlights">播客精选</option><option value="knowledge_digest">知识精华</option><option value="opinion_first">观点先行</option><option value="clean_speech">口播清理</option></select></label>
    <label>预设提示词（可修改）<textarea aria-label="预设提示词" value={prompts[preset]} maxLength={12000} disabled={busy} onChange={event=>setPrompts({...prompts,[preset]:event.target.value})} /></label><button type="button" disabled={busy} onClick={()=>setPrompts({...prompts,[preset]:presetDefaults[preset as keyof typeof presetDefaults]})}>恢复此预设默认提示词</button><p className="helper-text">上面的文字会实际发送给 AI；下面可补充本次要求。切换预设保留各自草稿。</p>
    <label className="instructions-label">剪辑要求<textarea aria-label="剪辑要求" value={instructions} maxLength={12000} disabled={busy} onChange={event => setInstructions(event.target.value)} placeholder="例如：提取不同观点的精彩讨论，保留限定条件和必要背景" /></label>
    <details><summary>高级参数</summary><label>正文模式<select aria-label="正文模式" value={bodyMode} disabled={busy} onChange={event=>setBodyMode(event.target.value as "continuous"|"compact")}><option value="continuous">连续正文（保留中间全部内容）</option><option value="compact">精简拼接（允许跳切）</option></select></label><p className="helper-text">时长为目标，完整内容可略超时；不为凑数截断句子。</p><label>数量<input aria-label="数量" type="number" value={count} disabled={busy} onChange={event => setCount(Number(event.target.value))} /></label><label>最短秒数<input aria-label="最短秒数" type="number" value={min} disabled={busy || preset === "clean_speech"} onChange={event => setMin(Number(event.target.value))} /></label><label>最长秒数<input aria-label="最长秒数" type="number" value={max} disabled={busy || preset === "clean_speech"} onChange={event => setMax(Number(event.target.value))} /></label><label>不同作品间素材重叠上限（%）<input aria-label="源内容重复上限" type="number" value={overlap} disabled={busy||count===1} onChange={event => setOverlap(Number(event.target.value))} /></label><p className="helper-text">{count===1?"只生成一条时不适用，无需设置。":"控制不同候选共享的原素材比例，以较短作品为分母。例如两条各60秒，30%允许最多18秒重叠；不限制钩子在本条正文中再次出现。"}</p><label className="checkbox-field"><input type="checkbox" checked={hook} disabled={busy} onChange={event => setHook(event.target.checked)} />约五秒原话钩子</label></details>
    {!ready && <p className="helper-text">完成转录后可生成候选。</p>}<p className="helper-text">DeepSeek 仅接收转录文本 · 可能计费</p>
    {error && <p role="alert">{error}</p>}<button disabled={!ready || busy}>生成候选</button>
  </form>;
}
