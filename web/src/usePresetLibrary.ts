import { useCallback, useEffect, useRef, useState } from "react";
import { createGenerationPreset, deleteGenerationPreset, listGenerationPresets, renameGenerationPreset, updateGenerationPreset, type GenerationPreset } from "./api";
import { generationValidationError, type GenerationDraft } from "./generationDraft";

export function usePresetLibrary() {
  const [presets, setPresets] = useState<GenerationPreset[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const locked = useRef(false);
  useEffect(()=>{
    const controller = new AbortController();
    setLoading(true); setLoadError("");
    listGenerationPresets(controller.signal).then(value=>{
      if (!controller.signal.aborted) {setPresets(value);setLoading(false);}
    }).catch(reason=>{
      if (!controller.signal.aborted) {setLoadError(reason instanceof Error?reason.message:"无法读取自定义预设");setLoading(false);}
    });
    return ()=>controller.abort();
  }, [retry]);
  const refresh = useCallback(()=>setRetry(value=>value+1),[]);
  async function mutate<T>(operation:()=>Promise<T>, apply:(value:T)=>void):Promise<T|undefined> {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError("");
    try {const value=await operation();apply(value);return value;}
    catch (reason) {setError(reason instanceof Error?reason.message:"预设操作失败");}
    finally {locked.current=false;setBusy(false);}
  }
  function upsert(preset:GenerationPreset) {
    setPresets(current=>[...current.filter(item=>item.preset_id!==preset.preset_id),preset].sort((a,b)=>a.name.localeCompare(b.name)));
  }
  function save(name:string,draft:GenerationDraft,id?:string) {
    const validation = generationValidationError(draft);
    if (validation) {setError(validation);return Promise.resolve(undefined);}
    return mutate(()=>id?updateGenerationPreset(id,name,draft):createGenerationPreset(name,draft),upsert);
  }
  return {presets, loading, loadError, error, busy, refresh,
    create:(name:string,draft:GenerationDraft)=>save(name,draft),
    update:(id:string,name:string,draft:GenerationDraft)=>save(name,draft,id),
    rename:(id:string,name:string)=>mutate(()=>renameGenerationPreset(id,name),upsert),
    remove:(id:string)=>mutate(()=>deleteGenerationPreset(id),()=>setPresets(current=>current.filter(item=>item.preset_id!==id))),
  };
}
export type PresetLibraryState = ReturnType<typeof usePresetLibrary>;
