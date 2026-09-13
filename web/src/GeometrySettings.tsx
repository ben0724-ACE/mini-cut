export interface GeometryOptions {aspect_ratio:"original"|"16:9"|"9:16"|"1:1"|"4:5"; resolution:720|1080; fit:"pad"|"crop"}
export const defaultGeometry:GeometryOptions={aspect_ratio:"original",resolution:1080,fit:"pad"};
export function GeometrySettings({value,onChange,disabled=false,label="导出"}:{value:Partial<GeometryOptions>;onChange:(value:GeometryOptions)=>void;disabled?:boolean;label?:string}) {
  const current={...defaultGeometry,...value};
  return <fieldset disabled={disabled}><legend>{label}画幅</legend>
    <label>{label}比例<select value={current.aspect_ratio} onChange={event=>onChange({...current,aspect_ratio:event.target.value as GeometryOptions["aspect_ratio"]})}>{["original","16:9","9:16","1:1","4:5"].map(ratio=><option key={ratio} value={ratio}>{ratio==="original"?"原始比例":ratio}</option>)}</select></label>
    <label>{label}分辨率<select value={current.resolution} onChange={event=>onChange({...current,resolution:Number(event.target.value) as GeometryOptions["resolution"]})}><option value={720}>720 档</option><option value={1080}>1080 档</option></select></label>
    <label>{label}适配<select value={current.fit} onChange={event=>onChange({...current,fit:event.target.value as GeometryOptions["fit"]})}><option value="pad">完整加边框</option><option value="crop">居中裁切</option></select></label>
    <p className="helper-text">居中裁切可能裁掉边缘人物或源字幕。</p>
    <details><summary>画幅说明</summary><p className="helper-text">保持比例，不拉伸、不追踪人物。原始比例不放大；720 / 1080 档最长边上限为 1280 / 1920。</p></details>
  </fieldset>;
}
