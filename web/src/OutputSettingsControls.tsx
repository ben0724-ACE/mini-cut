import {GeometrySettings} from "./GeometrySettings";
import {ExportPresetControls} from "./ExportPresetControls";
import type {ExportDraft,ExportOptions} from "./exportSettingsApi";

export function OutputSettingsControls({draft,onChange,disabled=false,label="导出",sourceUrl,sourceTime,batch=false,showSubtitles=true}:{draft:ExportDraft;onChange:(draft:ExportDraft)=>void;disabled?:boolean;label?:string;sourceUrl?:string;sourceTime?:number;batch?:boolean;showSubtitles?:boolean}){
  function change(options:Partial<ExportOptions>){onChange({...draft,options:{...draft.options,...options}});}
  return <>
    <ExportPresetControls draft={draft} onChange={onChange} disabled={disabled} batch={batch}/>
    <GeometrySettings label={label} value={draft.options} onChange={change} disabled={disabled} sourceUrl={sourceUrl} sourceTime={sourceTime}/>
    {showSubtitles&&<label>{batch?"批量字幕":"字幕方式"}<select disabled={disabled} value={draft.options.subtitle_mode} onChange={event=>change({subtitle_mode:event.target.value as ExportOptions["subtitle_mode"]})}><option value="soft">软字幕（播放器可开关）</option><option value="burned">烧录字幕（画面内）</option></select></label>}
    <details><summary>音频处理</summary>
      <label>{batch?"批量淡入淡出（毫秒）":"切点淡入淡出（毫秒）"}<input type="number" min={0} max={500} disabled={disabled} value={draft.options.audio_fade_ms} onChange={event=>change({audio_fade_ms:Number(event.target.value)})}/></label>
      <label>{batch?"批量降噪":"降噪"}<select disabled={disabled} value={draft.options.denoiser_id} onChange={event=>change({denoiser_id:event.target.value as ExportOptions["denoiser_id"]})}><option value="none">关闭</option><option value="afftdn">FFmpeg 降噪</option></select></label>
      <p className="helper-text">音频处理默认关闭，不生成新语音。</p>
    </details>
  </>;
}
