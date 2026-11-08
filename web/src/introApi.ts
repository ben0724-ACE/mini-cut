import type {IntroSettings} from "./api";
export interface IntroStyle {duration_ms:number;font_id:string|null;music:boolean;motion:boolean;motion_style:"fade"|"rise";motion_strength:number;transition_ms:number;audio_id:string|null}
export const defaultIntroStyle=():IntroStyle=>({duration_ms:5000,font_id:null,music:true,motion:true,motion_style:"rise",motion_strength:1,transition_ms:600,audio_id:null});
export function introStyle(value:IntroSettings):IntroStyle{return {duration_ms:value.duration_ms,font_id:value.font_id??null,music:value.music,motion:value.motion??false,motion_style:value.motion_style??"fade",motion_strength:value.motion_strength??1,transition_ms:value.transition_ms??0,audio_id:value.audio_id??null};}
export interface ExportIntroSettings extends IntroStyle {enabled:boolean}
export const exportIntroSettings=(value?:IntroSettings|null):ExportIntroSettings=>({...(value?introStyle(value):defaultIntroStyle()),enabled:!!value});
export interface IntroAudio {audio_id:string;name:string;duration_ms:number}
async function request<T>(url:string,init?:RequestInit):Promise<T>{const response=await fetch(url,init);if(!response.ok){const body=await response.json().catch(()=>null);throw new Error(typeof body?.detail==="string"?body.detail:`导读请求失败（${response.status}）`);}return response.json();}
export const uploadIntroAudio=(file:File)=>request<IntroAudio>(`/api/intro-audio?name=${encodeURIComponent(file.name)}`,{method:"POST",body:file});
export const getIntroAudio=(id:string,signal?:AbortSignal)=>request<IntroAudio>(`/api/intro-audio/${encodeURIComponent(id)}`,{signal});
export const introAudioUrl=(id:string)=>`/api/intro-audio/${encodeURIComponent(id)}/media`;
