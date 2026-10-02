import { useEffect, useState } from "react";
import { activeGenerationPrompt, applyGenerationPreset, normalizeGenerationDraft, type GenerationDraft } from "./generationDraft";
import type { PresetLibraryState } from "./usePresetLibrary";

const builtins:Record<string,string> = {podcast_highlights:"播客精选",knowledge_digest:"知识精华",opinion_first:"观点先行",clean_speech:"口播清理"};
export function PresetControls({draft:rawDraft,onChange,disabled,library}:{draft:GenerationDraft;onChange:(draft:GenerationDraft)=>void;disabled:boolean;library:PresetLibraryState}) {
  const draft = normalizeGenerationDraft(rawDraft);
  const [selection, setSelection] = useState(draft.custom_preset_id?`custom:${draft.custom_preset_id}`:draft.preset);
  const [name, setName] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const selectedId = selection.startsWith("custom:") ? selection.slice(7) : null;
  const current = library.presets.find(item=>item.preset_id===selectedId);
  const applied = !!current && current.preset_id === draft.custom_preset_id;
  const busy = disabled || library.busy;
  const canManage = !busy && !library.loading && !library.loadError;
  useEffect(()=>{setSelection(draft.custom_preset_id?`custom:${draft.custom_preset_id}`:draft.preset);},[draft.custom_preset_id,draft.preset]);
  useEffect(()=>{setName(current?.name??(selectedId===draft.custom_preset_id?draft.custom_preset_name??"":""));setConfirmDelete(false);},[current?.preset_id,current?.name,selectedId,draft.custom_preset_id,draft.custom_preset_name]);
  function select(value:string) {
    setNotice(""); setConfirmDelete(false);
    setSelection(value);
    if (!value.startsWith("custom:")) {
      onChange({...draft,preset:value,custom_preset_id:null,custom_preset_name:null,custom_prompt:null});
    }
  }
  function apply(mode:"workflow"|"prompt") {
    if (!current) return;
    onChange(applyGenerationPreset(draft,current,mode));
    setNotice(mode === "workflow" ? `已应用“${current.name}”的提示词和全部生成参数` : `已应用“${current.name}”的剪辑提示词，保留当前高级参数`);
  }
  async function saveAs() {
    const saved = await library.create(name.trim(),draft);
    if (saved) {onChange({...draft,custom_preset_id:saved.preset_id,custom_preset_name:saved.name,custom_prompt:activeGenerationPrompt(draft)});setNotice(`已保存“${saved.name}”，所有项目均可使用`);}
  }
  async function update() {
    if (!current || !applied) return;
    const saved = await library.update(current.preset_id,current.name,draft);
    if (saved) {onChange({...draft,custom_preset_name:saved.name});setNotice(`已用当前提示词和参数更新“${saved.name}”`);}
  }
  async function rename() {
    if (!current) return;
    const saved = await library.rename(current.preset_id,name.trim());
    if (saved) {if(applied)onChange({...draft,custom_preset_name:saved.name});setNotice(`已重命名为“${saved.name}”`);}
  }
  async function remove() {
    if (!current) return;
    const deleted = await library.remove(current.preset_id);
    if (deleted) {if(!applied)setSelection(draft.custom_preset_id?`custom:${draft.custom_preset_id}`:draft.preset);setConfirmDelete(false);setNotice(`已删除“${current.name}”；当前草稿和历史配置仍保留`);}
  }
  return <div className="preset-controls">
    <label>预设<select aria-label="预设" value={selection} disabled={busy} onChange={event=>select(event.target.value)}>
      <optgroup label="内置预设">{Object.entries(builtins).map(([id,label])=><option key={id} value={id}>{label}</option>)}</optgroup>
      {!!library.presets.length&&<optgroup label="我的预设">{library.presets.map(item=><option key={item.preset_id} value={`custom:${item.preset_id}`}>{item.name}</option>)}</optgroup>}
      {selectedId&&!current&&<option value={selection}>{draft.custom_preset_name??"自定义预设"}（{library.loading?"读取中":library.loadError?"库暂不可用":"已删除或未找到"}）</option>}
    </select></label>
    {current&&<div className="preset-apply-controls" role="group" aria-label="应用内容">
      <span>应用内容</span>
      <div className="preset-apply-actions">
        <button type="button" disabled={busy||library.loading} onClick={()=>apply("prompt")}>仅提示词</button>
        <button type="button" disabled={busy||library.loading} onClick={()=>apply("workflow")}>全部参数</button>
      </div>
      <p className="helper-text">仅提示词保留当前参数；全部参数一并替换。</p>
    </div>}
    {library.loading&&<p role="status">正在读取自定义预设…</p>}
    {library.loadError&&<p role="alert">{library.loadError}<button type="button" disabled={busy} onClick={library.refresh}>重试</button></p>}
    {draft.custom_preset_id&&!current&&!library.loading&&!library.loadError&&<p className="helper-text">预设已删除或未找到，当前配置保留。</p>}
    {draft.custom_preset_id&&<p className="helper-text">基础选材方式：{builtins[draft.preset]??draft.preset}</p>}
    <details className="preset-management"><summary>管理预设</summary>
      <p className="helper-text">另存或更新会修改共享预设，不影响已有草稿和作品。</p>
      <label>预设名称<input aria-label="预设名称" value={name} maxLength={80} disabled={busy} onChange={event=>setName(event.target.value)} onKeyDown={event=>{if(event.key==="Enter")event.preventDefault();}} placeholder="例如：知识访谈 · 双语短片" /></label>
      <div className="preset-actions">
        <button type="button" disabled={!canManage||!name.trim()} onClick={()=>void saveAs()}>另存为预设</button>
        <button type="button" disabled={!canManage||!applied} onClick={()=>void update()}>更新预设</button>
        <button type="button" disabled={!canManage||!current||!name.trim()||name.trim()===current.name} onClick={()=>void rename()}>重命名预设</button>
        <button type="button" className="danger-button" disabled={!canManage||!current} onClick={()=>setConfirmDelete(true)}>删除预设</button>
        <button type="button" disabled={busy||library.loading} onClick={library.refresh}>刷新预设</button>
      </div>
      {confirmDelete&&current&&<div className="preset-delete-confirm"><p>删除“{current.name}”？已应用的草稿和生成历史仍然保留。</p><button type="button" className="danger-button" disabled={!canManage} onClick={()=>void remove()}>确认删除预设</button><button type="button" disabled={busy} onClick={()=>setConfirmDelete(false)}>取消删除</button></div>}
    </details>
    {library.busy&&<p role="status">正在保存预设库变更…</p>}
    {library.error&&<p role="alert">{library.error}</p>}
    {notice&&<p role="status">{notice}</p>}
  </div>;
}
