import {useRef,type ReactNode} from "react";

export type ExportMode="single"|"batch";
export function ExportModePanels({mode,onChange,single,batch}:{mode:ExportMode;onChange:(mode:ExportMode)=>void;single:ReactNode;batch:ReactNode}){
  const root=useRef<HTMLDivElement>(null);
  function select(next:ExportMode){onChange(next);const scroll=root.current?.closest(".tool-scroll");if(scroll)scroll.scrollTop=0;}
  return <div ref={root} className="export-mode-panels">
    <div className="export-mode-switch" role="group" aria-label="导出模式">
      <button type="button" aria-pressed={mode==="single"} onClick={()=>select("single")}>单个</button>
      <button type="button" aria-pressed={mode==="batch"} onClick={()=>select("batch")}>批量</button>
    </div>
    <div hidden={mode!=="single"}>{single}</div>
    <div hidden={mode!=="batch"}>{batch}</div>
  </div>;
}
