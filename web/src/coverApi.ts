export interface CoverBox {x:number;y:number;width:number;height:number}
export interface CoverDesign {
  mode:"first_frame"|"design";aspect_ratio:"9:16"|"16:9"|"1:1"|"3:4";
  background_color:string;background_image:string|null;background_scale:number;background_x:number;background_y:number;
  frame_ms:number|null;frame:CoverBox;frame_fit:"contain"|"crop";title:string;title_box:CoverBox;
  font_id:string|null;font_size:number;bold:boolean;text_color:string;stroke_color:string;stroke_width:number;align:"left"|"center"|"right";
}
export interface CoverRecord {version:number;design:CoverDesign;fonts?:{id:string;name:string}[]}
export function coverRoute(project:string,collection:string,output:string){return `/api/projects/${encodeURIComponent(project)}/highlights/${encodeURIComponent(collection)}/outputs/${encodeURIComponent(output)}/cover`;}
async function checked(response:Response){if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(typeof body.detail==="string"?body.detail:"封面操作失败，请检查输入或稍后重试");}return response;}
export async function loadCover(route:string,revision:number,signal?:AbortSignal):Promise<CoverRecord>{return (await checked(await fetch(`${route}?revision=${revision}`,{signal}))).json();}
export async function saveCover(route:string,revision:number,base_version:number,design:CoverDesign):Promise<CoverRecord>{return (await checked(await fetch(route,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({revision,base_version,design})}))).json();}
export async function previewCover(route:string,revision:number,design:CoverDesign,signal?:AbortSignal){const response=await checked(await fetch(`${route}/preview`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({revision,design}),signal}));return {blob:await response.blob(),warnings:JSON.parse(response.headers.get("X-Cover-Warnings")??"[]") as string[]};}
export async function uploadCoverBackground(route:string,revision:number,file:File):Promise<string>{const value=await (await checked(await fetch(`${route}/background?revision=${revision}`,{method:"POST",body:file}))).json();return value.image_id;}
