import type {GeometryOptions} from "./GeometrySettings";

export interface ExportOptions extends GeometryOptions {subtitle_mode:"soft"|"burned";audio_fade_ms:number;denoiser_id:"none"|"afftdn"}
export interface ExportDraft {options:ExportOptions;overrides:Record<string,GeometryOptions>;preset_id:string|null;preset_name:string|null}
export interface ExportPreset {preset_id:string;name:string;options:ExportOptions;created_at:string;updated_at:string}
export interface ExportDraftResponse {source:"saved"|"project"|"default";draft:ExportDraft}
export const defaultExportOptions=():ExportOptions=>({aspect_ratio:"original",resolution:1080,fit:"pad",crop_left:0,crop_right:0,crop_top:0,crop_bottom:0,subtitle_mode:"soft",audio_fade_ms:0,denoiser_id:"none"});
export const defaultExportDraft=():ExportDraft=>({options:defaultExportOptions(),overrides:{},preset_id:null,preset_name:null});
export const exportPresetsChanged="minicut:export-presets-changed";
export function exportSettingsRoute(project:string,collection:string,output?:string){return `/api/projects/${encodeURIComponent(project)}/highlights/${encodeURIComponent(collection)}${output?`/outputs/${encodeURIComponent(output)}`:""}/export-settings`;}
async function request<T>(url:string,init?:RequestInit):Promise<T>{
  const response=await fetch(url,init);
  if(!response.ok){const data=await response.json().catch(()=>null);throw new Error(typeof data?.detail==="string"?data.detail:`导出设置请求失败（${response.status}）`);}
  return response.json();
}
export const getExportDraft=(route:string,signal?:AbortSignal)=>request<ExportDraftResponse>(route,{signal});
export const saveExportDraft=(route:string,draft:ExportDraft)=>request<ExportDraftResponse>(route,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(draft)});
export const listExportPresets=(signal?:AbortSignal)=>request<ExportPreset[]>("/api/export-presets",{signal});
export const writeExportPreset=(name:string,options:ExportOptions,id?:string)=>request<ExportPreset>(`/api/export-presets${id?`/${encodeURIComponent(id)}`:""}`,{method:id?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name,options})});
export const renameExportPreset=(id:string,name:string)=>request<ExportPreset>(`/api/export-presets/${encodeURIComponent(id)}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({name})});
export const deleteExportPreset=(id:string)=>request(`/api/export-presets/${encodeURIComponent(id)}`,{method:"DELETE"});
