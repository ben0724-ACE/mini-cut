import { useState, type ReactNode } from "react";
export type WorkbenchTab = "generate" | "edit" | "export";
export function Workbench({sidebar,preview,generate,edit,exportPanel,tab:controlledTab,onTabChange}:{sidebar:ReactNode;preview:ReactNode;generate:ReactNode;edit:ReactNode;exportPanel:ReactNode;tab?:WorkbenchTab;onTabChange?:(tab:WorkbenchTab)=>void}) {
  const [localTab,setLocalTab]=useState<WorkbenchTab>("generate");
  const tab=controlledTab??localTab;
  function setTab(value:string){const next=value as WorkbenchTab;setLocalTab(next);onTabChange?.(next);}
  return <div className="workbench"><aside className="workbench-sidebar">{sidebar}</aside><section className="workbench-preview" aria-label="预览区">{preview}</section><aside className="workbench-tools"><div role="tablist" aria-label="工作面板">{[["generate","生成"],["edit","编辑"],["export","导出"]].map(([id,title])=><button type="button" role="tab" key={id} id={`tab-${id}`} aria-controls={`panel-${id}`} aria-selected={tab===id} onClick={()=>setTab(id)}>{title}</button>)}</div><div className="tool-scroll"><section id="panel-generate" role="tabpanel" aria-labelledby="tab-generate" hidden={tab!=="generate"}>{generate}</section><section id="panel-edit" role="tabpanel" aria-labelledby="tab-edit" hidden={tab!=="edit"}>{edit}</section><section id="panel-export" role="tabpanel" aria-labelledby="tab-export" hidden={tab!=="export"}>{exportPanel}</section></div></aside></div>;
}
