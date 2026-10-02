import { useEffect, useId, useRef, useState, type ReactNode } from "react";
export type WorkbenchTab = "generate" | "edit" | "export";
const tabs: { id: WorkbenchTab; title: string }[] = [
  { id: "generate", title: "生成" },
  { id: "edit", title: "编辑" },
  { id: "export", title: "导出" },
];
export function Workbench({sidebar,preview,generate,edit,exportPanel,tab:controlledTab,onTabChange,initialTab="generate"}:{sidebar:ReactNode;preview:ReactNode;generate:ReactNode;edit:ReactNode;exportPanel:ReactNode;tab?:WorkbenchTab;onTabChange?:(tab:WorkbenchTab)=>void;initialTab?:WorkbenchTab}) {
  const [localTab,setLocalTab]=useState<WorkbenchTab>(initialTab);
  const [collapsed,setCollapsed]=useState(false);
  const [narrow,setNarrow]=useState(()=>window.matchMedia?.("(max-width: 800px)").matches??false);
  const collapseButton=useRef<HTMLButtonElement>(null);
  const expandButton=useRef<HTMLButtonElement>(null);
  const focusAfterToggle=useRef(false);
  useEffect(()=>{
    if(!window.matchMedia)return;
    const media=window.matchMedia("(max-width: 800px)");
    const update=()=>setNarrow(media.matches);
    update();media.addEventListener("change",update);
    return()=>media.removeEventListener("change",update);
  },[]);
  useEffect(()=>{
    if(!focusAfterToggle.current)return;
    focusAfterToggle.current=false;
    (collapsed?expandButton:collapseButton).current?.focus();
  },[collapsed]);
  const prefix=useId();
  const tab=controlledTab??localTab;
  function setTab(next:WorkbenchTab){setLocalTab(next);onTabChange?.(next);}
  function togglePanel(next:boolean){focusAfterToggle.current=true;setCollapsed(next);}
  function panelIcon(expand:boolean){return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><path d={narrow?"M3 16h18":"M16 3v18"}/><path d={narrow?(expand?"M8 8l4 4 4-4":"M8 12l4-4 4 4"):(expand?"M11 8l-4 4 4 4":"M8 8l4 4-4 4")}/></svg>;}
  const panelName=narrow?"工具面板":"右侧面板";
  return <div className={`workbench ${collapsed?"tools-collapsed":""}`}><aside className="workbench-sidebar">{sidebar}</aside><section className="workbench-preview" aria-label="预览区"><div className="preview-toolbar"><span className="eyebrow">作品预览</span>{collapsed&&<button ref={expandButton} className="panel-toggle" type="button" aria-expanded={false} aria-controls={`${prefix}-tools`} onClick={()=>togglePanel(false)}>{panelIcon(true)}展开{panelName}</button>}</div>{preview}</section><aside id={`${prefix}-tools`} className="workbench-tools" hidden={collapsed}><div className="workbench-tools-toolbar"><span className="eyebrow">工具面板</span><button ref={collapseButton} className="panel-toggle" type="button" aria-expanded={true} aria-controls={`${prefix}-tools`} onClick={()=>togglePanel(true)}>{panelIcon(false)}收起{panelName}</button></div><div role="tablist" aria-label="工作面板">{tabs.map(({id,title},index)=><button type="button" role="tab" key={id} id={`${prefix}-tab-${id}`} aria-controls={`${prefix}-panel-${id}`} aria-selected={tab===id} tabIndex={tab===id?0:-1} onClick={()=>setTab(id)} onKeyDown={event=>{
    let next=index;
    if(event.key==="ArrowRight")next=(index+1)%tabs.length;
    else if(event.key==="ArrowLeft")next=(index+tabs.length-1)%tabs.length;
    else if(event.key==="Home")next=0;
    else if(event.key==="End")next=tabs.length-1;
    else return;
    event.preventDefault();setTab(tabs[next].id);
    document.getElementById(`${prefix}-tab-${tabs[next].id}`)?.focus();
  }}>{title}</button>)}</div><div className="tool-scroll">{tabs.map(({id})=><section key={id} id={`${prefix}-panel-${id}`} role="tabpanel" tabIndex={0} aria-labelledby={`${prefix}-tab-${id}`} hidden={tab!==id}>{id==="generate"?generate:id==="edit"?edit:exportPanel}</section>)}</div></aside></div>;
}
