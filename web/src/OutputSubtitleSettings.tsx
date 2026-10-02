import { useEffect, useId, useRef, useState } from "react";
import { readHighlightTask, saveOutputSubtitleSettings, startOutputTranslation, type HighlightOutput, type HighlightResult, type SubtitleSettings } from "./api";

export function OutputSubtitleSettings({project,collection,plan,disabled,disabledReason,onUpdated,onDirty}:{project:string;collection:string;plan:HighlightOutput;disabled:boolean;disabledReason?:string;onUpdated:(result:HighlightResult)=>void;onDirty?:(dirty:boolean)=>void}) {
  const taskStorageKey=`minicut-translation:${project}:${collection}:${plan.output_id}`;
  const initial:SubtitleSettings={subtitle_mode:plan.subtitle_mode??plan.clips.find(c=>c.translation_language)?.subtitle_mode??"bilingual",subtitle_source_scale:plan.subtitle_source_scale??1,subtitle_translation_scale:plan.subtitle_translation_scale??1,subtitle_horizontal_percent:plan.subtitle_horizontal_percent??50,subtitle_bottom_percent:plan.subtitle_bottom_percent??10,subtitle_order:plan.subtitle_order??"source_first"};
  const [settings,setSettings]=useState(initial);
  const [language,setLanguage]=useState<"zh"|"en">(plan.clips.find(c=>c.translation_language)?.translation_language??"zh");
  const [taskId,setTaskId]=useState<string|undefined>(()=>window.localStorage.getItem(taskStorageKey)??undefined);
  const [saving,setSaving]=useState(false);
  const [submitting,setSubmitting]=useState(false);
  const requestLock=useRef(false);
  const translationHintId=useId();
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const missing=plan.clips.some(c=>!c.deleted&&!c.translation_text);
  const existingLanguage=plan.clips.find(c=>!c.deleted&&c.translation_text)?.translation_language;
  const changed=JSON.stringify(settings)!==JSON.stringify(initial);
  const controlsDisabled=disabled||saving||submitting||!!taskId;
  const valid=[
    [settings.subtitle_source_scale,0.7,1.5],
    [settings.subtitle_translation_scale,0.7,1.5],
    [settings.subtitle_horizontal_percent,20,80],
    [settings.subtitle_bottom_percent,5,40],
  ].every(([value,min,max])=>Number.isFinite(value)&&value>=min&&value<=max);
  const translationHint=disabled?(disabledReason??"先完成当前编辑或保存。")
    :submitting?"正在提交翻译任务…"
    :taskId?"正在翻译缺失字幕…"
    :saving?"正在保存字幕设置…"
    :changed?"设置未保存，保存或放弃后可翻译。"
    :!missing?"字幕已全部翻译。"
    :existingLanguage?"沿用已有译文语言。":"";
  function change(next:SubtitleSettings){setSettings(next);setMessage("");setError("");}
  async function save(){
    if(requestLock.current||controlsDisabled||!changed||!valid)return;
    requestLock.current=true;setSaving(true);setError("");setMessage("");
    try{onUpdated(await saveOutputSubtitleSettings(project,collection,plan.output_id,plan.revision,settings));setMessage("字幕设置已保存");}
    catch(reason){setError(reason instanceof Error?reason.message:"保存失败");}
    finally{requestLock.current=false;setSaving(false);}
  }
  async function translate(){
    if(requestLock.current||controlsDisabled||!missing||changed)return;
    requestLock.current=true;setSubmitting(true);setError("");setMessage("");
    try{
      const task=await startOutputTranslation(project,collection,plan.output_id,plan.revision,language);
      setTaskId(task.task_id);
      window.localStorage.setItem(taskStorageKey,task.task_id);
    }catch(reason){setError(reason instanceof Error?reason.message:"启动翻译失败");}
    finally{requestLock.current=false;setSubmitting(false);}
  }
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
    <p className="helper-text">保存生成新版本；缺少译文时显示原文。</p>
    <div className="subtitle-settings-grid">
      <label>字幕显示<select aria-label="全局字幕显示" value={settings.subtitle_mode??"bilingual"} disabled={controlsDisabled} onChange={e=>change({...settings,subtitle_mode:e.target.value as "bilingual"|"translated"|"source"})}><option value="bilingual">双语（原文＋译文）</option><option value="translated">仅译文</option><option value="source">仅原文</option></select></label>
      <label>原文字号（倍）<input aria-label="原文字号" type="number" min="0.7" max="1.5" step="0.1" value={settings.subtitle_source_scale} disabled={controlsDisabled} onChange={e=>change({...settings,subtitle_source_scale:Number(e.target.value)})} /></label>
      <label>译文字号（倍）<input aria-label="译文字号" type="number" min="0.7" max="1.5" step="0.1" value={settings.subtitle_translation_scale} disabled={controlsDisabled} onChange={e=>change({...settings,subtitle_translation_scale:Number(e.target.value)})} /></label>
      <label>横向位置（%）<input aria-label="字幕横向位置" type="number" min="20" max="80" step="5" value={settings.subtitle_horizontal_percent} disabled={controlsDisabled} onChange={e=>change({...settings,subtitle_horizontal_percent:Number(e.target.value)})} /></label>
      <label>距底部（%）<input aria-label="字幕距底部" type="number" min="5" max="40" step="1" value={settings.subtitle_bottom_percent} disabled={controlsDisabled} onChange={e=>change({...settings,subtitle_bottom_percent:Number(e.target.value)})} /></label>
      <label>双语上下顺序<select aria-label="双语上下顺序" value={settings.subtitle_order} disabled={controlsDisabled} onChange={e=>change({...settings,subtitle_order:e.target.value as "source_first"|"translation_first"})}><option value="source_first">原文在上 · 译文在下</option><option value="translation_first">译文在上 · 原文在下</option></select></label>
    </div>
    <div className="action-row"><button type="button" className="primary-button" disabled={controlsDisabled||!changed||!valid} onClick={()=>void save()}>{saving?"正在保存…":"保存字幕设置"}</button><button type="button" disabled={controlsDisabled||!changed} onClick={()=>change(initial)}>放弃设置</button></div>
    {changed&&<p id={translationHintId} className="helper-text draft-notice" role="status">{translationHint}</p>}
    {!valid&&<p role="alert">原文和译文字号需在 0.7–1.5 倍之间，横向位置需在 20–80% 之间，距底部需在 5–40% 之间。</p>}
    <div className="subtitle-translation-action"><label>翻译语言<select aria-label="翻译语言" aria-describedby={translationHint?translationHintId:undefined} value={language} disabled={controlsDisabled||!!existingLanguage} onChange={e=>{setLanguage(e.target.value as "zh"|"en");setMessage("");setError("");}}><option value="zh">简体中文</option><option value="en">英语</option></select></label><button type="button" aria-describedby={translationHint?translationHintId:undefined} disabled={controlsDisabled||!missing||changed} onClick={()=>void translate()}>{submitting?"正在提交…":taskId?"正在翻译…":"翻译字幕"}</button></div>
    <p className="helper-text">仅翻译缺失字幕，保留已有译文。可能产生费用，请校对。</p>{translationHint&&!changed&&<p id={translationHintId} className="helper-text" role="status">{translationHint}</p>}{error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
  </section>;
}
