import { useId, useState, type ReactNode } from "react";
export type WorkbenchTab = "generate" | "edit" | "export";
const tabs: { id: WorkbenchTab; title: string }[] = [
  { id: "generate", title: "生成" },
  { id: "edit", title: "编辑" },
  { id: "export", title: "导出" },
];
export function Workbench({sidebar,preview,generate,edit,exportPanel,tab:controlledTab,onTabChange,initialTab="generate"}:{sidebar:ReactNode;preview:ReactNode;generate:ReactNode;edit:ReactNode;exportPanel:ReactNode;tab?:WorkbenchTab;onTabChange?:(tab:WorkbenchTab)=>void;initialTab?:WorkbenchTab}) {
  const [localTab,setLocalTab]=useState<WorkbenchTab>(initialTab);
  const [collapsed,setCollapsed]=useState(false);
  const prefix=useId();
  const tab=controlledTab??localTab;
  function setTab(next:WorkbenchTab){setLocalTab(next);onTabChange?.(next);}
  return <div className={`workbench ${collapsed?"tools-collapsed":""}`}><aside className="workbench-sidebar">{sidebar}</aside><section className="workbench-preview" aria-label="预览区"><div className="preview-toolbar"><span className="eyebrow">作品预览</span><button type="button" aria-expanded={!collapsed} aria-controls={`${prefix}-tools`} onClick={()=>setCollapsed(value=>!value)}>{collapsed?"展开工作面板":"收起工作面板"}</button></div>{preview}</section><aside id={`${prefix}-tools`} className="workbench-tools" hidden={collapsed}><div role="tablist" aria-label="工作面板">{tabs.map(({id,title},index)=><button type="button" role="tab" key={id} id={`${prefix}-tab-${id}`} aria-controls={`${prefix}-panel-${id}`} aria-selected={tab===id} tabIndex={tab===id?0:-1} onClick={()=>setTab(id)} onKeyDown={event=>{
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
