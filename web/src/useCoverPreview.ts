import {useEffect,useRef,useState} from "react";
import {previewCover,type CoverDesign} from "./coverApi";

// Keep one render in flight and coalesce edits into the latest pending design.
export function useCoverPreview(route:string,revision:number,design:CoverDesign|undefined){
  const [image,setImage]=useState("");const [warnings,setWarnings]=useState<string[]>([]);
  const [error,setError]=useState("");const [rendering,setRendering]=useState(false);
  const latest=useRef(design);const schedule=useRef<()=>void>(()=>{});
  const enabled=design?.mode==="design";
  useEffect(()=>{
    const controller=new AbortController();let timer:ReturnType<typeof setTimeout>|undefined;
    let active=false;let requested:CoverDesign|undefined;let started=0;let imageUrl="";
    setImage("");setWarnings([]);setError("");setRendering(false);
    if(!enabled)return;
    function enqueue(){
      if(controller.signal.aborted||active||timer!==undefined||latest.current?.mode!=="design"||latest.current===requested)return;
      setRendering(true);
      timer=setTimeout(()=>{timer=undefined;void render();},Math.max(0,250-(Date.now()-started)));
    }
    async function render(){
      const snapshot=latest.current;if(!snapshot||snapshot.mode!=="design")return;
      active=true;requested=snapshot;started=Date.now();
      try{
        const value=await previewCover(route,revision,snapshot,controller.signal);
        if(controller.signal.aborted)return;
        const url=URL.createObjectURL(value.blob);if(imageUrl)URL.revokeObjectURL(imageUrl);imageUrl=url;
        setImage(url);setWarnings(value.warnings);setError("");
      }catch(reason){
        if(!controller.signal.aborted&&latest.current===snapshot)setError(reason instanceof Error?reason.message:"封面预览失败");
      }finally{
        active=false;
        if(!controller.signal.aborted){if(latest.current!==snapshot)enqueue();else setRendering(false);}
      }
    }
    schedule.current=enqueue;
    return()=>{controller.abort();clearTimeout(timer);schedule.current=()=>{};if(imageUrl)URL.revokeObjectURL(imageUrl);};
  },[route,revision,enabled]);
  useEffect(()=>{latest.current=design;if(enabled){setRendering(true);schedule.current();}},[design,enabled,route,revision]);
  return {image,warnings,error,rendering};
}
