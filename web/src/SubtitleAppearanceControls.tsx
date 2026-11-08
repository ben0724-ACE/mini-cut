import {useEffect,useState} from "react";
import {defaultSubtitleStyle,listSubtitleFonts,type HighlightOutput,type SubtitleSettings,type SubtitleStyle} from "./api";

export function subtitleSettingsFromPlan(plan:HighlightOutput):SubtitleSettings {
  return {subtitle_mode:plan.subtitle_mode??null,subtitle_source_scale:plan.subtitle_source_scale??1,subtitle_translation_scale:plan.subtitle_translation_scale??1,subtitle_horizontal_percent:plan.subtitle_horizontal_percent??50,subtitle_bottom_percent:plan.subtitle_bottom_percent??10,subtitle_order:plan.subtitle_order??"source_first",subtitle_style:plan.subtitle_style??null};
}
export function defaultSubtitleSettings():SubtitleSettings {
  return {subtitle_mode:"bilingual",subtitle_source_scale:1,subtitle_translation_scale:1,subtitle_horizontal_percent:50,subtitle_bottom_percent:10,subtitle_order:"source_first",subtitle_style:defaultSubtitleStyle()};
}
export function validSubtitleSettings(settings:SubtitleSettings):boolean {
  const style=settings.subtitle_style??defaultSubtitleStyle();
  return [[style.source_size,16,200],[style.translation_size,16,200],[style.stroke_width,0,12],[style.shadow_width,0,12],[style.background_opacity,0,100],[settings.subtitle_horizontal_percent,20,80],[settings.subtitle_bottom_percent,5,40]].every(([value,min,max])=>Number.isInteger(value)&&value>=min&&value<=max);
}
export function SubtitleAppearanceControls({settings,onChange,disabled=false,onValid}:{settings:SubtitleSettings;onChange:(settings:SubtitleSettings)=>void;disabled?:boolean;onValid?:(valid:boolean)=>void}) {
  const style=settings.subtitle_style??defaultSubtitleStyle();
  const [fonts,setFonts]=useState<{id:string;name:string}[]>([]);
  const [fontsError,setFontsError]=useState("");const [fontsLoading,setFontsLoading]=useState(true);const [fontRequest,setFontRequest]=useState(0);
  const controlsDisabled=disabled;
  const valid=validSubtitleSettings(settings);
  const missingFonts=([["source_font_id","原文"],["translation_font_id","译文"]] as const).filter(([key])=>!!style[key]&&!fontsLoading&&!fontsError&&!fonts.some(font=>font.id===style[key])).map(([,label])=>label);
  const fontMissing=missingFonts.length>0;
  const selectedFont=!!style.source_font_id||!!style.translation_font_id;
  useEffect(()=>{onValid?.(valid&&!fontMissing&&(!selectedFont||(!fontsLoading&&!fontsError)));},[valid,fontMissing,selectedFont,fontsLoading,fontsError,onValid]);
  useEffect(()=>{const controller=new AbortController();setFontsLoading(true);setFontsError("");void listSubtitleFonts(controller.signal).then(value=>{if(!controller.signal.aborted)setFonts(value);}).catch(reason=>{if(!controller.signal.aborted)setFontsError(reason instanceof Error?reason.message:"读取字体失败");}).finally(()=>{if(!controller.signal.aborted)setFontsLoading(false);});return()=>controller.abort();},[fontRequest]);
  function change(next:SubtitleSettings){onChange(next);}
  function changeStyle(patch:Partial<SubtitleStyle>){change({...settings,subtitle_style:{...style,...patch}});}
  function fontSelect(key:"source_font_id"|"translation_font_id",label:string){
    const id=style[key];
    return <label>{label}<select aria-label={label} value={id??""} disabled={controlsDisabled||fontsLoading} onChange={e=>changeStyle({[key]:e.target.value||null})}><option value="">默认中文字体</option>{id&&!fonts.some(font=>font.id===id)&&<option value={id}>{fontsLoading?"正在读取已选字体…":"已选字体不可用"}</option>}{fonts.map(font=><option key={font.id} value={font.id}>{font.name}</option>)}</select></label>;
  }
  return <>
    <div className="subtitle-settings-grid">
      <label>字幕显示<select aria-label="全局字幕显示" value={settings.subtitle_mode??"bilingual"} disabled={controlsDisabled} onChange={e=>change({...settings,subtitle_mode:e.target.value as "bilingual"|"translated"|"source"})}><option value="bilingual">双语（原文＋译文）</option><option value="translated">仅译文</option><option value="source">仅原文</option></select></label>
      {fontSelect("source_font_id","原文字体")}
      <label>原文字号<input aria-label="原文字号" type="number" min="16" max="200" step="1" value={Number.isNaN(style.source_size)?"":style.source_size} disabled={controlsDisabled} onChange={e=>changeStyle({source_size:e.target.valueAsNumber})} /></label>
      {fontSelect("translation_font_id","译文字体")}
      <label>译文字号<input aria-label="译文字号" type="number" min="16" max="200" step="1" value={Number.isNaN(style.translation_size)?"":style.translation_size} disabled={controlsDisabled} onChange={e=>changeStyle({translation_size:e.target.valueAsNumber})} /></label>
      <label>横向位置（%）<input aria-label="字幕横向位置" type="number" min="20" max="80" step="5" value={settings.subtitle_horizontal_percent} disabled={controlsDisabled} onChange={e=>change({...settings,subtitle_horizontal_percent:Number(e.target.value)})} /></label>
      <label>距底部（%）<input aria-label="字幕距底部" type="number" min="5" max="40" step="1" value={settings.subtitle_bottom_percent} disabled={controlsDisabled} onChange={e=>change({...settings,subtitle_bottom_percent:Number(e.target.value)})} /></label>
      <label>双语上下顺序<select aria-label="双语上下顺序" value={settings.subtitle_order} disabled={controlsDisabled} onChange={e=>change({...settings,subtitle_order:e.target.value as "source_first"|"translation_first"})}><option value="source_first">原文在上 · 译文在下</option><option value="translation_first">译文在上 · 原文在下</option></select></label>
    </div>
    <p className="helper-text">字号、描边和阴影以画面短边 1080 像素为基准；720p 自动缩为 2/3，相对大小保持一致。原文和译文分别设置字体和字号，颜色、描边、阴影与背景效果共用。</p>
    {!settings.subtitle_style&&<p className="helper-text">此作品仍使用旧版排版。首次保存设置后启用下方新样式，请更新成片预览核对。</p>}
    {fontsLoading&&<p role="status">正在读取本机字体…</p>}
    {fontsError&&<p role="alert">{fontsError}<button type="button" disabled={controlsDisabled} onClick={()=>setFontRequest(value=>value+1)}>重试读取字体</button></p>}
    {fontMissing&&<p role="alert">{missingFonts.join("、")}字体在本机不可用，请重新选择。</p>}
    <fieldset disabled={controlsDisabled} className="subtitle-effects"><legend>字幕效果</legend><div className="subtitle-settings-grid">
      <label>文字颜色<input aria-label="字幕文字颜色" type="color" value={style.text_color} onChange={e=>changeStyle({text_color:e.target.value})}/></label>
      <label>描边宽度<input aria-label="字幕描边宽度" type="number" min="0" max="12" step="1" value={Number.isNaN(style.stroke_width)?"":style.stroke_width} onChange={e=>changeStyle({stroke_width:e.target.valueAsNumber})}/></label>
      <label>描边颜色<input aria-label="字幕描边颜色" type="color" value={style.stroke_color} onChange={e=>changeStyle({stroke_color:e.target.value})}/></label>
      <label>阴影强度<input aria-label="字幕阴影强度" type="number" min="0" max="12" step="1" value={Number.isNaN(style.shadow_width)?"":style.shadow_width} onChange={e=>changeStyle({shadow_width:e.target.valueAsNumber})}/></label>
      <label>阴影颜色<input aria-label="字幕阴影颜色" type="color" value={style.shadow_color} onChange={e=>changeStyle({shadow_color:e.target.value})}/></label>
    </div><label className="checkbox-field"><input aria-label="字幕加粗" type="checkbox" checked={style.bold} onChange={e=>changeStyle({bold:e.target.checked})}/>加粗</label><p className="helper-text">描边宽度或阴影强度设为 0 可关闭对应效果。</p>
    <label className="checkbox-field"><input aria-label="字幕背景框" type="checkbox" checked={style.background_enabled} onChange={e=>changeStyle({background_enabled:e.target.checked})}/>半透明背景框</label>
    {style.background_enabled&&<div className="subtitle-settings-grid"><label>背景颜色<input aria-label="字幕背景颜色" type="color" value={style.background_color} onChange={e=>changeStyle({background_color:e.target.value})}/></label><label>背景不透明度（%）<input aria-label="字幕背景不透明度" type="number" min="0" max="100" step="1" value={Number.isNaN(style.background_opacity)?"":style.background_opacity} onChange={e=>changeStyle({background_opacity:e.target.valueAsNumber})}/></label></div>}
    </fieldset>
    {!valid&&<p role="alert">字号需为 16–200 的整数，描边和阴影需为 0–12，背景不透明度需为 0–100%；横向位置需为 20–80%，距底部需为 5–40%，均需填写整数。</p>}
  </>;
}
