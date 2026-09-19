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
  const [hookSeconds, setHookSeconds] = useState(5);
  const [hook, setHook] = useState(false); const [overlap, setOverlap] = useState(30);
  const [error, setError] = useState("");
  return <form className="transcription-controls" onSubmit={event => {
    event.preventDefault();
    if (!ready || busy) return;
    if (!Number.isInteger(count) || count < 1 || count > 10 || !Number.isFinite(min) || !Number.isFinite(max) || min <= 0 || max < min || overlap < 0 || overlap > 100 || !prompts[preset]?.trim()) {setError("请检查数量（1–10）与时长范围、重复比例"); return;}
    if(hook && (!Number.isFinite(hookSeconds) || hookSeconds < 1 || hookSeconds > 60)){setError("钩子目标时长需在 1–60 秒之间");return;}
    setError(""); onSubmit({body_mode:bodyMode,preset, preset_prompt:prompts[preset], instructions, count, min_ms: preset === "clean_speech" ? null : Math.round(min * 1000), max_ms: preset === "clean_speech" ? null : Math.round(max * 1000), hook_ms: hook ? Math.round(hookSeconds * 1000) : null, max_source_overlap: count === 1 ? 1 : overlap / 100});
  }}>
    <h2>AI 生成</h2><label>预设<select aria-label="预设" value={preset} disabled={busy} onChange={event => setPreset(event.target.value)}><option value="podcast_highlights">播客精选</option><option value="knowledge_digest">知识精华</option><option value="opinion_first">观点先行</option><option value="clean_speech">口播清理</option></select></label>
    <label>预设提示词（可修改）<textarea aria-label="预设提示词" value={prompts[preset]} maxLength={12000} disabled={busy} onChange={event=>setPrompts({...prompts,[preset]:event.target.value})} /></label><button type="button" disabled={busy} onClick={()=>setPrompts({...prompts,[preset]:presetDefaults[preset as keyof typeof presetDefaults]})}>恢复此预设默认提示词</button><p className="helper-text">上面的文字会实际发送给 AI；下面可补充本次要求。切换预设保留各自草稿。</p>
    <p className="helper-text">{preset === "clean_speech" ? (bodyMode === "continuous" ? "当前为连续正文：保留范围内停顿、重复和重说。若需删去这些片段，请在高级参数中选择精简拼接。" : "当前为精简拼接：可省略重复或失败重说片段，正文保持原顺序；不保证逐字去除停顿。") : preset === "opinion_first" ? "观点先行只影响选材，不重排正文，也不自动开启钩子；开场预告由下方钩子开关单独控制。" : "预设决定选材方向；正文模式决定能否跳切，钩子开关决定是否添加开场预告。"}</p>
    <label className="instructions-label">剪辑要求<textarea aria-label="剪辑要求" value={instructions} maxLength={12000} disabled={busy} onChange={event => setInstructions(event.target.value)} placeholder="例如：提取不同观点的精彩讨论，保留限定条件和必要背景" /></label>
    <details><summary>高级参数</summary><label>正文模式<select aria-label="正文模式" value={bodyMode} disabled={busy} onChange={event=>setBodyMode(event.target.value as "continuous"|"compact")}><option value="continuous">连续正文（保留中间全部内容）</option><option value="compact">精简拼接（允许跳切）</option></select></label><p className="helper-text">时长为目标，完整内容可略超时；不为凑数截断句子。</p><label>数量<input aria-label="数量" type="number" value={count} disabled={busy} onChange={event => setCount(Number(event.target.value))} /></label><label>最短秒数<input aria-label="最短秒数" type="number" value={min} disabled={busy || preset === "clean_speech"} onChange={event => setMin(Number(event.target.value))} /></label><label>最长秒数<input aria-label="最长秒数" type="number" value={max} disabled={busy || preset === "clean_speech"} onChange={event => setMax(Number(event.target.value))} /></label><label>不同作品间素材重叠上限（%）<input aria-label="源内容重复上限" type="number" value={overlap} disabled={busy||count===1} onChange={event => setOverlap(Number(event.target.value))} /></label><p className="helper-text">{count===1?"只生成一条时不适用，无需设置。":"控制不同候选共享的原素材比例，以较短作品为分母。例如两条各60秒，30%允许最多18秒重叠；不限制钩子在本条正文中再次出现。"}</p><label className="checkbox-field"><input type="checkbox" checked={hook} disabled={busy} onChange={event => setHook(event.target.checked)} />原话开场钩子</label>{hook && <><label>钩子目标秒数<input aria-label="钩子目标秒数" type="number" min={1} max={60} step={0.1} value={hookSeconds} disabled={busy} onChange={event=>setHookSeconds(Number(event.target.value))} /></label><p className="helper-text">默认 5 秒，可设 1–60 秒。优先完整原话，允许略偏离目标，找不到合适内容则省略；生成后仍可微调范围。此时长不含钩子与正文之间的转场。</p></>}</details>
    {!ready && <p className="helper-text">完成转录后可生成候选。</p>}<p className="helper-text">DeepSeek 仅接收转录文本 · 可能计费</p>
    {error && <p role="alert">{error}</p>}<button disabled={!ready || busy}>生成候选</button>
  </form>;
}
