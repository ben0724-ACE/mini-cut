import type {SubtitleSettings} from "./api";
import type {ExportDraft,ExportOptions} from "./exportSettingsApi";

export function outputSettingsLabel(options:ExportOptions):string {
  const short=options.resolution;
  const dimensions={"16:9":`${short*16/9}×${short}`,"9:16":`${short}×${short*16/9}`,"1:1":`${short}×${short}`,"4:5":`${short}×${short*5/4}`};
  return `${options.aspect_ratio==="original"?`原始比例 · ${short} 档`:`${options.aspect_ratio} · ${dimensions[options.aspect_ratio]}`} · ${options.subtitle_mode==="burned"?"烧录字幕":"软字幕"}`;
}

export function OutputSettingsSummary({options,presetName,subtitleSettings}:{options:ExportOptions;presetName?:ExportDraft["preset_name"];subtitleSettings?:Partial<SubtitleSettings>}) {
  const subtitles=options.subtitle_settings??subtitleSettings;
  const crops=[options.crop_top??0,options.crop_bottom??0,options.crop_left??0,options.crop_right??0];
  const audio=[options.audio_fade_ms?`淡入淡出 ${options.audio_fade_ms} 毫秒`:null,options.denoiser_id!=="none"?"降噪开启":null].filter(Boolean).join(" · ")||"关闭";
  return <div className="output-settings-summary">
    <p>{outputSettingsLabel(options)}</p>
    <dl>
      {presetName&&<><dt>应用的预设</dt><dd>{presetName}</dd></>}
      <dt>画面适配</dt><dd>{options.fit==="crop"?"居中裁切":"完整加边框"}</dd>
      <dt>裁剪</dt><dd>{crops.some(Boolean)?`上 ${crops[0]}% · 下 ${crops[1]}% · 左 ${crops[2]}% · 右 ${crops[3]}%`:"未裁剪"}</dd>
      <dt>字幕排版</dt><dd>{subtitles?[
        subtitles.subtitle_mode==="source"?"仅原文":subtitles.subtitle_mode==="translated"?"仅译文":subtitles.subtitle_mode==="bilingual"?"双语":"沿用作品显示方式",
        subtitles.subtitle_style&&subtitles.subtitle_mode!=="translated"?`原文 ${subtitles.subtitle_style.source_size} 号`:null,
        subtitles.subtitle_style&&subtitles.subtitle_mode!=="source"?`译文 ${subtitles.subtitle_style.translation_size} 号`:null,
      ].filter(Boolean).join(" · "):"沿用作品字幕设置"}</dd>
      <dt>音频处理</dt><dd>{audio}</dd>
    </dl>
  </div>;
}

export function effectiveOutputOptions(draft:ExportDraft,output?:string):ExportOptions {
  return {...draft.options,...(output?draft.overrides[output]:{})};
}
