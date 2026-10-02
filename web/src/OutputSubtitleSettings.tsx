import { useEffect, useState } from "react";
import { readHighlightTask, saveOutputSubtitleSettings, startOutputTranslation, type HighlightOutput, type HighlightResult, type SubtitleSettings } from "./api";

export function OutputSubtitleSettings({project,collection,plan,disabled,onUpdated,onDirty}:{project:string;collection:string;plan:HighlightOutput;disabled:boolean;onUpdated:(result:HighlightResult)=>void;onDirty?:(dirty:boolean)=>void}) {
  const taskStorageKey=`minicut-translation:${project}:${collection}:${plan.output_id}`;
  const initial:SubtitleSettings={subtitle_mode:plan.subtitle_mode??plan.clips.find(c=>c.translation_language)?.subtitle_mode??"bilingual",subtitle_source_scale:plan.subtitle_source_scale??1,subtitle_translation_scale:plan.subtitle_translation_scale??1,subtitle_horizontal_percent:plan.subtitle_horizontal_percent??50,subtitle_bottom_percent:plan.subtitle_bottom_percent??10,subtitle_order:plan.subtitle_order??"source_first"};
  const [settings,setSettings]=useState(initial);
  const [language,setLanguage]=useState<"zh"|"en">(plan.clips.find(c=>c.translation_language)?.translation_language??"zh");
  const [taskId,setTaskId]=useState<string|undefined>(()=>window.localStorage.getItem(taskStorageKey)??undefined);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const missing=plan.clips.some(c=>!c.deleted&&!c.translation_text);
  const existingLanguage=plan.clips.find(c=>!c.deleted&&c.translation_text)?.translation_language;
  const changed=JSON.stringify(settings)!==JSON.stringify(initial);
  useEffect(()=>{onDirty?.(changed);return()=>onDirty?.(false);},[changed,onDirty]);
  useEffect(()=>{
    if(!taskId)return;
    let active=true;
    const poll=async()=>{
      try{
        const task=await readHighlightTask(project,taskId);
        if(!active)return;
        if(task.status==="succeeded"&&task.result){window.localStorage.removeItem(taskStorageKey);setTaskId(undefined);setMessage("译文已生成，请逐句校对");onUpdated(task.result);}
        else if(task.status==="failed"||task.status==="cancelled"){window.localStorage.removeItem(taskStorageKey);setTaskId(undefined);setError(task.error??"翻译失败");}
      }catch(reason){if(active){window.localStorage.removeItem(taskStorageKey);setTaskId(undefined);setError(reason instanceof Error?reason.message:"读取翻译任务失败");}}
    };
    void poll();const timer=window.setInterval(()=>void poll(),1500);
    return()=>{active=false;window.clearInterval(timer);};
  },[project,taskId,taskStorageKey,onUpdated]);
  return <section className="subtitle-settings" aria-label="本作品字幕设置">
    <h3>本作品字幕设置</h3>
    <p className="helper-text">作用于当前作品全部字幕；保存后生成新版本。未翻译的句子仍显示原文。字号与位置用于烧录字幕的成片预览及导出。</p>
    <div className="subtitle-settings-grid">
      <label>字幕显示<select aria-label="全局字幕显示" value={settings.subtitle_mode??"bilingual"} disabled={disabled||saving||!!taskId} onChange={e=>setSettings({...settings,subtitle_mode:e.target.value as "bilingual"|"translated"|"source"})}><option value="bilingual">双语（原文＋译文）</option><option value="translated">仅译文</option><option value="source">仅原文</option></select></label>
      <label>原文字号（倍）<input aria-label="原文字号" type="number" min="0.7" max="1.5" step="0.1" value={settings.subtitle_source_scale} disabled={disabled||saving||!!taskId} onChange={e=>setSettings({...settings,subtitle_source_scale:Number(e.target.value)})} /></label>
      <label>译文字号（倍）<input aria-label="译文字号" type="number" min="0.7" max="1.5" step="0.1" value={settings.subtitle_translation_scale} disabled={disabled||saving||!!taskId} onChange={e=>setSettings({...settings,subtitle_translation_scale:Number(e.target.value)})} /></label>
      <label>横向位置（%）<input aria-label="字幕横向位置" type="number" min="20" max="80" step="5" value={settings.subtitle_horizontal_percent} disabled={disabled||saving||!!taskId} onChange={e=>setSettings({...settings,subtitle_horizontal_percent:Number(e.target.value)})} /></label>
      <label>距底部（%）<input aria-label="字幕距底部" type="number" min="5" max="40" step="1" value={settings.subtitle_bottom_percent} disabled={disabled||saving||!!taskId} onChange={e=>setSettings({...settings,subtitle_bottom_percent:Number(e.target.value)})} /></label>
      <label>双语上下顺序<select aria-label="双语上下顺序" value={settings.subtitle_order} disabled={disabled||saving||!!taskId} onChange={e=>setSettings({...settings,subtitle_order:e.target.value as "source_first"|"translation_first"})}><option value="source_first">原文在上 · 译文在下</option><option value="translation_first">译文在上 · 原文在下</option></select></label>
    </div>
    <button disabled={disabled||saving||!!taskId||!changed||settings.subtitle_source_scale<0.7||settings.subtitle_source_scale>1.5||settings.subtitle_translation_scale<0.7||settings.subtitle_translation_scale>1.5||settings.subtitle_horizontal_percent<20||settings.subtitle_horizontal_percent>80||settings.subtitle_bottom_percent<5||settings.subtitle_bottom_percent>40} onClick={async()=>{setSaving(true);setError("");try{onUpdated(await saveOutputSubtitleSettings(project,collection,plan.output_id,plan.revision,settings));setMessage("字幕设置已保存");}catch(reason){setError(reason instanceof Error?reason.message:"保存失败");}finally{setSaving(false);}}}>保存字幕设置</button>
    <div className="subtitle-translation-action"><label>翻译语言<select aria-label="翻译语言" value={language} disabled={disabled||saving||!!taskId||!!existingLanguage} onChange={e=>setLanguage(e.target.value as "zh"|"en")}><option value="zh">简体中文</option><option value="en">英语</option></select></label><button disabled={disabled||saving||!!taskId||!missing||changed} onClick={async()=>{setError("");setMessage("");try{const task=await startOutputTranslation(project,collection,plan.output_id,plan.revision,language);window.localStorage.setItem(taskStorageKey,task.task_id);setTaskId(task.task_id);}catch(reason){setError(reason instanceof Error?reason.message:"启动翻译失败");}}}>{taskId?"正在翻译…":"翻译字幕"}</button></div>
    <p className="helper-text">点击“翻译字幕”后才会调用模型；已有译文会保留，只翻译缺失的句子。生成后请逐句校对。</p>{changed&&<p className="helper-text">请先保存字幕设置，再翻译缺失字幕。</p>}{error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
  </section>;
}
