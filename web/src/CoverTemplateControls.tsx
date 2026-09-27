import {useEffect,useRef,useState} from "react";
import {applyCoverTemplate,coverRoute,type CoverApplyMode,type CoverDesign} from "./coverApi";
import {useCoverTemplateLibrary} from "./useCoverTemplateLibrary";

export function CoverTemplateControls({project,collection,output,revision,design,onChange,disabled,onBusy}:{project:string;collection:string;output:string;revision:number;design:CoverDesign;onChange:(design:CoverDesign)=>void;disabled:boolean;onBusy:(busy:boolean)=>void}){
  const library=useCoverTemplateLibrary();const [selection,setSelection]=useState(design.template_id??"");
  const [name,setName]=useState("");const [notice,setNotice]=useState("");const [confirmDelete,setConfirmDelete]=useState(false);
  const [applying,setApplying]=useState(false);const [error,setError]=useState("");const lock=useRef(false);
  const current=library.templates.find(item=>item.template_id===selection);
  const appliedTemplate=library.templates.find(item=>item.template_id===design.template_id);
  const applied=!!current&&current.template_id===design.template_id;
  const busy=disabled||library.busy||applying;const canManage=!busy&&!library.loading&&!library.loadError;
  const source={project_id:project,collection_id:collection,output_id:output,revision,design};
  useEffect(()=>{setSelection(design.template_id??"");},[design.template_id]);
  useEffect(()=>{setName(current?.name??(selection===design.template_id?design.template_name??"":""));setConfirmDelete(false);},[current?.template_id,current?.name,selection]);
  useEffect(()=>{onBusy(library.busy||applying);return()=>onBusy(false);},[library.busy,applying,onBusy]);
  async function apply(mode:CoverApplyMode){if(!current||lock.current)return;lock.current=true;setApplying(true);setError("");try{const next=await applyCoverTemplate(coverRoute(project,collection,output),revision,current.template_id,mode,design);onChange(next);setNotice(`已应用“${current.name}”的${mode==="title"?"标题样式":"全部设计"}；标题文字和选帧保留，请保存封面设计。`);}catch(reason){setError(reason instanceof Error?reason.message:"应用模板失败");}finally{lock.current=false;setApplying(false);}}
  async function saveAs(){const saved=await library.create(name.trim(),source);if(saved){onChange({...design,template_id:saved.template_id,template_name:saved.name});setNotice(`已保存“${saved.name}”，所有项目均可使用。`);}}
  async function update(){if(!current||!applied)return;const saved=await library.update(current.template_id,current.name,source);if(saved){onChange({...design,template_name:saved.name});setNotice(`已用当前设计更新“${saved.name}”；其他作品的封面保持原样。`);}}
  async function rename(){if(!current)return;const saved=await library.rename(current.template_id,name.trim());if(saved){if(applied)onChange({...design,template_name:saved.name});setNotice(`已重命名为“${saved.name}”。`);}}
  async function remove(){if(!current)return;const removed=await library.remove(current.template_id);if(removed){if(!applied)setSelection(design.template_id??"");setConfirmDelete(false);setNotice(`已删除“${current.name}”；已应用的封面和导出图片仍保留。`);}}
  return <div className="preset-controls cover-template-controls">
    <label>封面模板<select aria-label="封面模板" value={selection} disabled={busy} onChange={event=>{setSelection(event.target.value);setNotice("");setError("");setConfirmDelete(false);}}><option value="">当前设计（未选择模板）</option>{!!library.templates.length&&<optgroup label="我的封面模板">{library.templates.map(item=><option key={item.template_id} value={item.template_id}>{item.name}</option>)}</optgroup>}{selection&&!current&&<option value={selection}>{design.template_name??"封面模板"}（{library.loading?"读取中":library.loadError?"库暂不可用":"已删除或未找到"}）</option>}</select></label>
    {current&&<div className="preset-apply-controls" role="group" aria-label="封面应用内容"><span>应用内容</span><div className="preset-apply-actions"><button type="button" disabled={busy||library.loading} onClick={()=>void apply("title")}>仅标题样式</button><button type="button" disabled={busy||library.loading} onClick={()=>void apply("all")}>全部设计</button></div><p className="helper-text">选择模板不会改变封面。点击按钮应用到草稿；标题文字和视频选帧始终保留。「仅标题样式」保留尺寸、背景与视频布局。</p></div>}
    {library.loading&&<p role="status">正在读取封面模板…</p>}{library.loadError&&<p role="alert">{library.loadError}<button type="button" disabled={busy} onClick={library.refresh}>重试读取封面模板库</button></p>}
    {design.template_id&&!appliedTemplate&&!library.loading&&!library.loadError&&<p className="helper-text">原模板已删除或未找到，当前封面仍可编辑、导出或另存为新模板。</p>}
    <details className="preset-management"><summary>管理我的封面模板</summary><p className="helper-text">编辑只改变当前封面草稿。另存或更新才修改全局模板；模板不保存作品标题和选帧，背景图片独立保存。</p><label>封面模板名称<input aria-label="封面模板名称" value={name} maxLength={80} disabled={busy||library.loading} onChange={event=>setName(event.target.value)} placeholder="例如：知识访谈 · 深色竖屏" /></label><div className="preset-actions"><button type="button" disabled={!canManage||!name.trim()||design.mode!=="design"} onClick={()=>void saveAs()}>另存为模板</button><button type="button" disabled={!canManage||!applied||design.mode!=="design"} onClick={()=>void update()}>用当前配置更新模板</button><button type="button" disabled={!canManage||!current||!name.trim()||name.trim()===current.name} onClick={()=>void rename()}>重命名模板</button><button type="button" disabled={!canManage||!current} onClick={()=>setConfirmDelete(true)}>删除模板</button><button type="button" disabled={busy||library.loading} onClick={library.refresh}>重新读取封面模板库</button></div>
      {confirmDelete&&current&&<div className="preset-delete-confirm"><p>删除“{current.name}”？已应用的封面和导出图片仍然保留。</p><button type="button" disabled={!canManage} onClick={()=>void remove()}>确认删除模板</button><button type="button" disabled={busy} onClick={()=>setConfirmDelete(false)}>取消删除</button></div>}
    </details>{(library.busy||applying)&&<p role="status">正在处理封面模板…</p>}{(error||library.error)&&<p role="alert">{error||library.error}</p>}{notice&&<p role="status">{notice}</p>}
  </div>;
}
