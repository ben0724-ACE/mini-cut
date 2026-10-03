import {GeometrySettings} from "./GeometrySettings";
import {SubtitleAppearanceControls,defaultSubtitleSettings} from "./SubtitleAppearanceControls";
import type {ExportDraft,ExportOptions} from "./exportSettingsApi";

export function OutputSettingsControls({draft,onChange,disabled=false,label="导出",sourceUrl,sourceTime,batch=false,showSubtitles=true,onSubtitleValid}:{draft:ExportDraft;onChange:(draft:ExportDraft)=>void;disabled?:boolean;label?:string;sourceUrl?:string;sourceTime?:number;batch?:boolean;showSubtitles?:boolean;onSubtitleValid?:(valid:boolean)=>void}){
  function change(options:Partial<ExportOptions>){onChange({...draft,options:{...draft.options,...options}});}
  return <>
    <GeometrySettings label={label} value={draft.options} onChange={change} disabled={disabled} sourceUrl={sourceUrl} sourceTime={sourceTime}/>
    {showSubtitles&&<label>{batch?"批量字幕":"字幕方式"}<select disabled={disabled} value={draft.options.subtitle_mode} onChange={event=>change({subtitle_mode:event.target.value as ExportOptions["subtitle_mode"]})}><option value="soft">软字幕（播放器可开关）</option><option value="burned">烧录字幕（画面内）</option></select></label>}
    {batch&&<details className="batch-subtitle-settings"><summary>批量字幕设置</summary><label className="checkbox-field"><input type="checkbox" aria-label="统一字幕排版" disabled={disabled} checked={!!draft.options.subtitle_settings} onChange={event=>{change({subtitle_settings:event.target.checked?defaultSubtitleSettings():null});onSubtitleValid?.(true);}}/>统一字幕排版与字体效果</label><p className="helper-text">关闭时沿用各作品的字幕设置；统一设置仅作用于本批次，字幕文字与时间轴保留。</p>{draft.options.subtitle_settings&&<SubtitleAppearanceControls settings={draft.options.subtitle_settings} onChange={subtitle_settings=>change({subtitle_settings})} disabled={disabled} onValid={onSubtitleValid}/>}</details>}
    <details><summary>音频处理</summary>
      <label>{batch?"批量淡入淡出（毫秒）":"切点淡入淡出（毫秒）"}<input type="number" min={0} max={500} disabled={disabled} value={draft.options.audio_fade_ms} onChange={event=>change({audio_fade_ms:Number(event.target.value)})}/></label>
      <label>{batch?"批量降噪":"降噪"}<select disabled={disabled} value={draft.options.denoiser_id} onChange={event=>change({denoiser_id:event.target.value as ExportOptions["denoiser_id"]})}><option value="none">关闭</option><option value="afftdn">FFmpeg 降噪</option></select></label>
      <p className="helper-text">音频处理默认关闭，不生成新语音。</p>
    </details>
  </>;
}
