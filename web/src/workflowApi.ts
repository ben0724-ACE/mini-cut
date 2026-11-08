import type {GenerationDraft} from "./generationDraft";
import type {HighlightResult, TranscriptionOptions, HighlightOutput} from "./api";
import type {ExportOptions} from "./exportSettingsApi";
import type {ExportLocationEntry} from "./exportNavigation";

export type WorkspaceMode="minimal"|"full";
export function readMode(project=""):WorkspaceMode {
  try{return localStorage.getItem(project?`minicut:mode:${project}`:"minicut:mode") === "minimal" ? "minimal" : "full";}catch{return "full";}
}
export function saveMode(mode:WorkspaceMode,project="") {
  try{localStorage.setItem("minicut:mode",mode);if(project)localStorage.setItem(`minicut:mode:${project}`,mode);}catch{/* The current view still switches if browser storage is unavailable. */}
}
export type WorkflowLayout=Pick<HighlightOutput,"subtitle_style"|"subtitle_mode"|"subtitle_source_scale"|"subtitle_translation_scale"|"subtitle_horizontal_percent"|"subtitle_bottom_percent"|"subtitle_order"|"hook_transition_ms"|"hook_transition_kind">;
export interface WorkflowBody {
  name:string;generation:GenerationDraft;transcription:TranscriptionOptions;export_options:ExportOptions;
  layout:WorkflowLayout;cover_template_id:string|null;auto_export:boolean;
}
export interface Workflow extends WorkflowBody {workflow_id:string;cover_template_name?:string|null;created_at:string;updated_at:string}
export interface WorkflowRun {
  task_id:string;asset_id:string;workflow_name:string;status:"pending"|"running"|"succeeded"|"failed"|"cancelled";
  phase:string;error:string|null;result:HighlightResult|null;exports:ExportLocationEntry[];child_task_ids:string[];cancel_requested?:boolean;
}
async function request<T>(url:string,init?:RequestInit):Promise<T>{
  const response=await fetch(url,init);
  if(!response.ok){const body=await response.json().catch(()=>null);throw new Error(typeof body?.detail==="string"?body.detail:`工作流请求失败（${response.status}）`);}
  return response.json();
}
export const workflowsChanged="minicut:workflows-changed";
export const listWorkflows=(signal?:AbortSignal)=>request<Workflow[]>("/api/workflows",{signal});
export const writeWorkflow=(body:WorkflowBody,id?:string)=>request<Workflow>(`/api/workflows${id?`/${encodeURIComponent(id)}`:""}`,{method:id?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:body.name,generation:body.generation,transcription:body.transcription,export_options:body.export_options,layout:body.layout,cover_template_id:body.cover_template_id,auto_export:body.auto_export})});
export const renameWorkflow=(id:string,name:string)=>request<Workflow>(`/api/workflows/${encodeURIComponent(id)}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({name})});
export const deleteWorkflow=(id:string)=>request(`/api/workflows/${encodeURIComponent(id)}`,{method:"DELETE"});
export const latestWorkflowRun=(project:string,signal?:AbortSignal)=>request<WorkflowRun|null>(`/api/projects/${encodeURIComponent(project)}/workflow-run`,{signal});
export const startWorkflowRun=(project:string,asset_id:string,workflow_id:string,key:string)=>request<WorkflowRun>(`/api/projects/${encodeURIComponent(project)}/workflow-runs`,{method:"POST",headers:{"Content-Type":"application/json","Idempotency-Key":key},body:JSON.stringify({asset_id,workflow_id})});
export const workflowAction=(project:string,id:string,action:"resume"|"cancel")=>request<WorkflowRun>(`/api/projects/${encodeURIComponent(project)}/workflow-runs/${encodeURIComponent(id)}/${action}`,{method:"POST"});
