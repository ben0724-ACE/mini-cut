import {useEffect,useRef,useState,type CSSProperties} from "react";
import type {HighlightOutput,IntroSettings} from "./api";
import {IntroAppearance,type IntroFont} from "./IntroAppearance";
import {defaultIntroStyle,introStyle} from "./introApi";
import {SaveStatus} from "./SaveStatus";
import {registerDraftGuard} from "./draftNavigation";

export function OutputIntro({plan,sourceUrl,aspectRatio="original",disabled,onDirty,onSaving,onSave}:{plan:HighlightOutput;sourceUrl:string;aspectRatio?:string;disabled:boolean;onDirty:(dirty:boolean)=>void;onSaving?:(saving:boolean)=>void;onSave:(intro:IntroSettings|null)=>Promise<void>}) {
  const savedIntro=plan.intro?{...plan.intro,...introStyle(plan.intro),music_version:2 as const}:null;
  const initial:IntroSettings=savedIntro??{title:plan.title,text:"",frame_ms:null,music_version:2,...defaultIntroStyle()};
  const [enabled,setEnabled]=useState(!!plan.intro);
  const [draft,setDraft]=useState<IntroSettings>(initial);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [sourceRatio,setSourceRatio]=useState(16/9);
  const [playing,setPlaying]=useState(false);
  const [animationKey,setAnimationKey]=useState(0);
  const [fonts,setFonts]=useState<IntroFont[]>([]);
  const [processing,setProcessing]=useState(false);
  const source=useRef<HTMLVideoElement>(null),background=useRef<HTMLVideoElement>(null);
  const lock=useRef(false);
  const changed=JSON.stringify(enabled?draft:null)!==JSON.stringify(savedIntro);
  const retained=plan.clips.filter(clip=>!clip.deleted);
  const defaultFrame=retained.find(clip=>clip.role==="body")?.start_ms??retained[0]?.start_ms??0;
  const frame=draft.frame_ms??defaultFrame;
  const frameValid=retained.some(clip=>frame>=clip.start_ms&&frame<clip.end_ms);
  const valid=!enabled||(!!draft.title.trim()&&draft.title.length<=80&&draft.text.length<=180&&Number.isFinite(draft.duration_ms)&&draft.duration_ms>=2000&&draft.duration_ms<=15000&&frameValid&&Number.isFinite(draft.transition_ms)&&(draft.transition_ms??0)>=0&&(draft.transition_ms??0)<=1500);
  useEffect(()=>{onDirty(changed||saving||processing);},[changed,saving,processing,onDirty]);
  useEffect(()=>{onSaving?.(saving||processing);return()=>onSaving?.(false);},[saving,processing,onSaving]);
  useEffect(()=>()=>onDirty(false),[onDirty]);
  useEffect(()=>{
    if(!changed)return;
    const unload=(event:BeforeUnloadEvent)=>event.preventDefault();
    window.addEventListener("beforeunload",unload);
    const unregister=registerDraftGuard(proceed=>{if(window.confirm("导读尚未保存，放弃修改并离开？"))proceed();});
    return()=>{window.removeEventListener("beforeunload",unload);unregister();};
  },[changed]);
  useEffect(()=>{for(const video of [source.current,background.current])if(video?.readyState)video.currentTime=frame/1000;},[frame]);
  function change(patch:Partial<IntroSettings>){setDraft(previous=>({...previous,...patch}));setError("");setPlaying(false);}
  async function save(){if(disabled||saving||processing||!valid||!changed||lock.current)return;lock.current=true;setSaving(true);setError("");try{await onSave(enabled?{...draft,title:draft.title.trim(),text:draft.text.trim()}:null);}catch(reason){setError(reason instanceof Error?reason.message:"导读保存失败");}finally{lock.current=false;setSaving(false);}}
  function useFrame(){const selected=Math.round((source.current?.currentTime??0)*1000);if(!retained.some(clip=>selected>=clip.start_ms&&selected<clip.end_ms)){setError("请选择当前作品保留片段中的画面。");return;}change({frame_ms:selected});}
  const ratio=aspectRatio==="original"?sourceRatio:Number(aspectRatio.split(":")[0])/Number(aspectRatio.split(":")[1]);
  const inheritedFont=fonts.find(font=>font.id===(plan.subtitle_style?.source_font_id??"configured"));
  const previewFont=(draft.font_id?fonts.find(font=>font.id===draft.font_id):inheritedFont)?.family;
  return <section className="output-intro" aria-label="开场导读设置">
    <h3>开场导读 <SaveStatus dirty={changed} saving={saving||processing}/></h3><p className="helper-text">视频帧虚化背景＋短标题与介绍，独立播放后进入原视频。保存只生成新版本；成片预览和导出时才渲染。字体、动效与配乐可通过上方「导出预设」统一保存。</p>
    <fieldset disabled={disabled||saving||processing}>
      <label className="checkbox-field"><input type="checkbox" checked={enabled} onChange={event=>{setEnabled(event.target.checked);setError("");}}/>启用开场导读</label>
      {enabled&&<>
        <IntroAppearance value={introStyle(draft)} onChange={style=>change({...style,music_version:2})} onBusy={setProcessing} onFonts={setFonts}/>
        <label>导读标题<input value={draft.title} onChange={event=>change({title:event.target.value})}/></label><div className="action-row intro-copy-actions"><span className="helper-text">{draft.title.length} / 80 字</span><button type="button" onClick={()=>change({title:plan.title})}>使用作品标题</button></div>
        <label>导读介绍<textarea rows={3} value={draft.text} onChange={event=>change({text:event.target.value})}/></label>
        <div className="action-row intro-copy-actions"><span className="helper-text">{draft.text.length} / 180 字</span><button type="button" disabled={!plan.social_copy} onClick={()=>change({text:plan.social_copy||""})}>使用作品简介</button></div>
        <p className="helper-text">完整带入已保存的作品简介，不调用 AI。请核对当前选段，按阅读需要延长导读或精简文字。</p>
        <div key={animationKey} className={`intro-layout-preview${playing&&draft.motion?` intro-layout--motion${draft.motion_style==="rise"?" intro-layout--rise":""}`:""}`} style={{aspectRatio:ratio,maxWidth:ratio<1?`${440*ratio}px`:"100%","--intro-duration":`${draft.duration_ms/1000}s`,"--intro-travel":`${12*(draft.motion_strength??1)}px`,"--intro-zoom":`${1.06*(1+.02*(draft.motion_strength??1))}`,"--intro-rise-zoom":`${1.06*(1+.045*(draft.motion_strength??1))}`,"--intro-drift":`${-.3*(draft.motion_strength??1)}%`} as CSSProperties} aria-label="导读排版示意" onAnimationEnd={event=>{if(event.animationName==="intro-background-motion"||event.animationName==="intro-camera-drift")setPlaying(false);}}>
          <video ref={background} src={sourceUrl} muted playsInline preload="metadata" onLoadedMetadata={()=>{if(background.current)background.current.currentTime=frame/1000;}}/>
          <div className="intro-layout-text" style={{fontFamily:previewFont}}><strong style={{fontSize:`${Math.min(1,1/ratio)*7.2}cqw`}}>{draft.title}</strong><p style={{fontSize:`${Math.min(1,1/ratio)*3.9}cqw`}}>{draft.text}</p></div>
        </div><p className="helper-text">排版示意。最终字体、虚化和音乐请通过「生成成片预览」核对。</p>
        {draft.motion&&<button type="button" disabled={!valid} onClick={()=>{setAnimationKey(value=>value+1);setPlaying(true);}}>播放动效示意</button>}
        <details><summary>选择背景帧 · {draft.frame_ms===null?"正文开头":`${(frame/1000).toFixed(2)} 秒`}</summary>
          <video ref={source} src={sourceUrl} className="player" controls muted preload="metadata" aria-label="选择导读背景帧" onLoadedMetadata={()=>{if(source.current){setSourceRatio(source.current.videoWidth/source.current.videoHeight||16/9);source.current.currentTime=frame/1000;}}}/>
          <div className="action-row"><button type="button" onClick={useFrame}>使用当前画面</button><button type="button" onClick={()=>change({frame_ms:null})}>恢复正文开头帧</button></div><p className="helper-text">可选择当前作品任一保留片段的画面。</p>
        </details>
        {!frameValid&&<p role="alert">背景帧已不在保留片段内，请重新选择或恢复默认帧。</p>}
        {!valid&&frameValid&&<p role="alert">请填写标题，控制标题在 80 字、介绍在 180 字以内，时长为 2–15 秒。</p>}
      </>}
    </fieldset>
    <div className="action-row"><button type="button" className="primary-button" disabled={disabled||saving||processing||!changed||!valid} onClick={()=>void save()}>{saving?"正在保存…":"保存导读"}</button><button type="button" disabled={disabled||saving||processing||!changed} onClick={()=>{setEnabled(!!plan.intro);setDraft(initial);setError("");}}>放弃导读修改</button></div>
    {disabled&&<p className="helper-text">历史版本只读；修改前请先保存或放弃其他编辑。</p>}
    {changed&&<p role="status" className="helper-text">导读有未保存修改，请保存或放弃后生成成片预览和导出。</p>}
    {error&&<p role="alert">{error}</p>}
  </section>;
}
