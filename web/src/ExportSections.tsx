import {useState, type ReactNode} from "react";

export function ExportSections({cover,children}:{cover:ReactNode;children:ReactNode}){
  const [section,setSection]=useState<"cover"|"frame">("frame");
  return <>
    <div className="export-section-switch" role="group" aria-label="导出内容">
      <button type="button" aria-pressed={section==="cover"} onClick={()=>setSection("cover")}>封面</button>
      <button type="button" aria-pressed={section==="frame"} onClick={()=>setSection("frame")}>画面</button>
    </div>
    <div hidden={section!=="cover"}>{cover}</div>
    <div hidden={section!=="frame"}>{children}</div>
  </>;
}
