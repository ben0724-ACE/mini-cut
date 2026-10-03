import {useEffect,useId,useRef,type ReactNode,type KeyboardEvent} from "react";
import {createPortal} from "react-dom";

export function WorkspaceDialog({open,title,onClose,children}:{open:boolean;title:string;onClose:()=>void;children:ReactNode}){
  const heading=useId();const dialog=useRef<HTMLElement>(null);
  useEffect(()=>{
    if(!open)return;
    const previous=document.activeElement instanceof HTMLElement?document.activeElement:null;
    const overflow=document.body.style.overflow;document.body.style.overflow="hidden";
    dialog.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return()=>{document.body.style.overflow=overflow;previous?.focus();};
  },[open]);
  function handleKey(event:KeyboardEvent<HTMLElement>){
    if(event.key==="Escape"){event.preventDefault();event.stopPropagation();onClose();return;}
    if(event.key!=="Tab")return;
    const controls=Array.from(event.currentTarget.querySelectorAll<HTMLElement>("button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,a[href],[tabindex='0']")).filter(control=>{
      const closed=control.closest("details:not([open])");return !control.closest("[hidden]")&&(!closed||control===closed.querySelector("summary"));
    });
    const first=controls[0],last=controls.at(-1);
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }
  return createPortal(<div className="workspace-dialog-backdrop" hidden={!open}>
    <section ref={dialog} role="dialog" aria-modal="true" aria-labelledby={heading} className="workspace-dialog" onKeyDown={handleKey}>
      <header className="workspace-dialog-heading"><h2 id={heading}>{title}</h2><button type="button" aria-label={`关闭${title}`} onClick={onClose}>关闭</button></header>
      <div className="workspace-dialog-body">{children}</div>
    </section>
  </div>,document.body);
}
