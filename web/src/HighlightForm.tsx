import { useState, type ReactNode } from "react";
import presetDefaults from "../../src/minicut/preset_prompts.json";
import { activeGenerationPrompt, defaultGenerationDraft, generationValidationError, normalizeGenerationDraft, type GenerationDraft } from "./generationDraft";

export interface HighlightBrief {preset: string; custom_preset_id?:string|null;custom_preset_name?:string|null;count: number; min_ms: number | null; max_ms: number | null; hook_ms: number | null; instructions?: string; editing_prompt?:string; max_source_overlap: number; preset_prompt?:string; body_mode?:"continuous"|"compact";translation_language?:"zh"|"en"|null;subtitle_mode?:"bilingual"|"translated"}
export function HighlightForm({ready, busy, onSubmit, draft: controlledDraft, onChange, presetControls, presetDefaultPrompt}: {ready: boolean; busy: boolean; onSubmit: (brief: HighlightBrief) => void; draft?: GenerationDraft; onChange?: (draft: GenerationDraft) => void;presetControls?:ReactNode;presetDefaultPrompt?:string|null}) {
  const [localDraft, setLocalDraft] = useState(defaultGenerationDraft);
  const draft = normalizeGenerationDraft(controlledDraft ?? localDraft);
  function update(changes: Partial<GenerationDraft>) {
    const next = {...draft, ...changes};
    setLocalDraft(next);
    onChange?.(next);
  }
  const {preset, prompts, count, min_seconds: min, max_seconds: max,
    hook_seconds: hookSeconds, hook_enabled: hook, overlap_percent: overlap, limit_duration: limitDuration,
    body_mode: bodyMode, translation_enabled: translate,
    translation_language: translationLanguage, subtitle_mode: subtitleMode} = draft;
  const [error, setError] = useState("");
  const clean = preset === "clean_speech";
  const prompt = activeGenerationPrompt(draft);
  const resetPrompt = draft.custom_preset_id ? presetDefaultPrompt : presetDefaults[preset as keyof typeof presetDefaults];
  return <form className="transcription-controls" onSubmit={event => {
    event.preventDefault();
    if (!ready || busy) return;
    const validation = generationValidationError(draft);
    if (validation) {setError(validation);return;}
    setError(""); onSubmit({custom_preset_id:draft.custom_preset_id??null,custom_preset_name:draft.custom_preset_name??null,translation_language:translate?translationLanguage:null,subtitle_mode:subtitleMode,body_mode:clean?"compact":bodyMode,preset, editing_prompt:prompt, count:clean?1:count, min_ms: preset === "clean_speech" || !limitDuration ? null : Math.round(min * 1000), max_ms: preset === "clean_speech" || !limitDuration ? null : Math.round(max * 1000), hook_ms: !clean && hook ? Math.round(hookSeconds * 1000) : null, max_source_overlap: clean || count === 1 ? 1 : overlap / 100});
  }}>
    <h2>AI 生成</h2><label>处理方式<select aria-label="处理方式" disabled={busy} value={clean?"cleanup":"highlights"} onChange={event=>update({preset:event.target.value==="cleanup"?"clean_speech":"podcast_highlights",custom_preset_id:null,custom_preset_name:null,custom_prompt:null})}><option value="highlights">精选片段</option><option value="cleanup">口播清理</option></select></label><section className="generation-preset-section" aria-label="生成预设">{presetControls??(!clean&&<label>预设<select aria-label="预设" value={preset} disabled={busy} onChange={event => update({preset:event.target.value,custom_preset_id:null,custom_preset_name:null,custom_prompt:null})}><option value="podcast_highlights">播客精选</option><option value="knowledge_digest">知识精华</option></select></label>)}</section>
    <label>剪辑提示词<textarea aria-label="剪辑提示词" value={prompt} maxLength={25000} disabled={busy} onChange={event=>update(draft.custom_preset_id?{custom_prompt:event.target.value}:{prompts:{...prompts,[preset]:event.target.value}})} /></label><button type="button" disabled={busy||resetPrompt==null} onClick={()=>{if(resetPrompt!=null)update(draft.custom_preset_id?{custom_prompt:resetPrompt}:{prompts:{...prompts,[preset]:resetPrompt}});}}>恢复此预设默认提示词</button><p className="helper-text">{clean?"可补充清理要求，例如保留某些语气词。":"选材方向、受众和本次要求统一写在这里，可直接修改。切换内置预设保留各自的提示词草稿。"}</p>
    <p className="helper-text">{clean ? "整段清理：删除明确口误、失败重说、重复和无意义填充词；超过 1 秒的静音压缩至约 0.3 秒，保留自然换气。只生成一条清理版，可试听并恢复删除。此流程不生成文案。" : "播客精选适合问答对话，知识精华适合个人陈述；可通过开场钩子突出重点。"}</p>
    {!clean&&<details><summary>高级参数</summary><label>正文模式<select aria-label="正文模式" value={bodyMode} disabled={busy} onChange={event=>update({body_mode:event.target.value as "continuous"|"compact"})}><option value="continuous">连续正文（保留中间全部内容）</option><option value="compact">精简拼接（允许跳切）</option></select></label><p className="helper-text">时长为目标，完整内容可略超时；不为凑数截断句子。</p><label>数量<input aria-label="数量" type="number" value={count} disabled={busy} onChange={event => update({count:Number(event.target.value)})} /></label><label className="checkbox-field"><input type="checkbox" checked={preset !== "clean_speech" && limitDuration} disabled={busy || preset === "clean_speech"} onChange={event=>update({limit_duration:event.target.checked})} />限制目标时长</label><label>最短秒数<input aria-label="最短秒数" type="number" value={min} disabled={busy || preset === "clean_speech" || !limitDuration} onChange={event => update({min_seconds:Number(event.target.value)})} /></label><label>最长秒数<input aria-label="最长秒数" type="number" value={max} disabled={busy || preset === "clean_speech" || !limitDuration} onChange={event => update({max_seconds:Number(event.target.value)})} /></label><label>不同作品间素材重叠上限（%）<input aria-label="源内容重复上限" type="number" value={overlap} disabled={busy||count===1} onChange={event => update({overlap_percent:Number(event.target.value)})} /></label><p className="helper-text">{count===1?"只生成一条时不适用，无需设置。":"控制不同候选共享的原素材比例，以较短作品为分母。例如两条各60秒，30%允许最多18秒重叠；不限制开场预告在本条正文中再次出现。"}</p><label className="checkbox-field"><input type="checkbox" checked={hook} disabled={busy} onChange={event => update({hook_enabled:event.target.checked})} />原话开场预告</label>{hook && <><label>开场预告目标秒数<input aria-label="开场预告目标秒数" type="number" min={1} max={60} step={0.1} value={hookSeconds} disabled={busy} onChange={event=>update({hook_seconds:Number(event.target.value)})} /></label><p className="helper-text">默认 5 秒，可设 1–60 秒。优先完整原话，允许略偏离目标，找不到合适内容则省略；生成后仍可微调范围。此时长不含开场预告与正文之间的转场。</p></>}</details>}
    <label className="checkbox-field"><input type="checkbox" checked={translate} disabled={busy} onChange={event=>update({translation_enabled:event.target.checked})} />翻译字幕</label>
    {translate&&<><label>翻译为<select aria-label="翻译为" value={translationLanguage} disabled={busy} onChange={e=>update({translation_language:e.target.value as "zh"|"en"})}><option value="zh">中文</option><option value="en">英文</option></select></label><label>字幕显示<select aria-label="字幕显示" value={subtitleMode} disabled={busy} onChange={e=>update({subtitle_mode:e.target.value as "bilingual"|"translated"})}><option value="bilingual">双语（原文＋译文）</option><option value="translated">仅译文</option></select></label><p className="helper-text">候选选定后，调用 DeepSeek 翻译候选字幕，可能计费；不改变原音。译文可在编辑中逐句修改，成片预览及导出使用所选显示方式。</p></>}
    {!ready && <p className="helper-text">完成转录后可生成候选。</p>}<p className="helper-text">DeepSeek 仅接收转录文本 · 可能计费</p>
    {error && <p role="alert">{error}</p>}<button className="primary-button generate-candidates-button" disabled={!ready || busy}>{clean?"一键清理":"生成候选"}</button>
  </form>;
}
