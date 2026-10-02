import type {ExportDraft,ExportOptions} from "./exportSettingsApi";

export function outputSettingsLabel(options:ExportOptions):string {
  const short=options.resolution;
  const dimensions={"16:9":`${short*16/9}×${short}`,"9:16":`${short}×${short*16/9}`,"1:1":`${short}×${short}`,"4:5":`${short}×${short*5/4}`};
  return `${options.aspect_ratio==="original"?`原始比例 · ${short} 档`:`${options.aspect_ratio} · ${dimensions[options.aspect_ratio]}`} · ${options.subtitle_mode==="burned"?"烧录字幕":"软字幕"}`;
}

export function OutputSettingsSummary({options,presetName}:{options:ExportOptions;presetName?:ExportDraft["preset_name"]}) {
  return <div className="output-settings-summary">
    <p>{outputSettingsLabel(options)}</p>
    <dl>
      {presetName&&<><dt>应用的预设</dt><dd>{presetName}</dd></>}
      <dt>画面适配</dt><dd>{options.fit==="crop"?"居中裁切":"完整加边框"}</dd>
      <dt>裁剪</dt><dd>上 {options.crop_top??0}% · 下 {options.crop_bottom??0}% · 左 {options.crop_left??0}% · 右 {options.crop_right??0}%</dd>
      <dt>音频处理</dt><dd>淡入淡出 {options.audio_fade_ms} 毫秒 · {options.denoiser_id==="none"?"降噪关闭":"FFmpeg 降噪"}</dd>
    </dl>
  </div>;
}

export function effectiveOutputOptions(draft:ExportDraft,output?:string):ExportOptions {
  return {...draft.options,...(output?draft.overrides[output]:{})};
}
