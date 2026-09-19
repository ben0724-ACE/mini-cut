import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { deleteProject } from "./api";
import type { ProjectDetail, ProjectSummary } from "./api";

interface Props {
  loadProjects: (signal?: AbortSignal) => Promise<ProjectSummary[]>;
  createProject: (name: string) => Promise<ProjectDetail>;
  onSelect: (projectId: string) => void;
}

export function ProjectHome({ loadProjects, createProject, onSelect }: Props) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState("");
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [createError, setCreateError] = useState("");
  const createButton = useRef<HTMLButtonElement>(null);
  function closeDialog() { setCreating(false); createButton.current?.focus(); }
  function dialogKey(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape" && !saving) closeDialog();
    if (event.key !== "Tab") return;
    const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("input:not(:disabled), button:not(:disabled)"));
    const first = controls[0]; const last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    loadProjects(controller.signal).then((value) => { if (!controller.signal.aborted) setProjects(value); }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "无法读取项目");
    });
    return () => controller.abort();
  }, [loadProjects, retry]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || saving) return;
    setSaving(true); setCreateError("");
    try { const project = await createProject(name.trim()); onSelect(project.project_id); }
    catch (reason: unknown) { setCreateError(reason instanceof Error ? reason.message : "创建失败"); }
    finally { setSaving(false); }
  }

  return <section className="project-home" aria-label="项目中心">
    <div className="home-intro"><p className="eyebrow">MINICUT / LOCAL STUDIO</p><h2>好内容，从精简开始。</h2><p>把长视频变成值得分享的片段。导入素材，让 AI 协助选材，由你决定最终剪辑。</p><div className="workflow-steps"><span>01 导入与转录</span><span>02 生成与审阅</span><span>03 导出作品</span></div></div>
    <header className="workspace-heading"><h1>我的项目</h1><button ref={createButton} className="primary-button" onClick={() => { setCreateError(""); setCreating(true); }}>新建项目</button></header>
    {deleteError && <p role="alert">{deleteError}</p>}
    {error ? <div><p role="alert">{error}</p><button onClick={() => setRetry(retry + 1)}>重试</button></div> : projects === null ? <p role="status">正在读取项目…</p> : projects.length === 0 ? <div className="empty-state"><span className="empty-state-icon" aria-hidden="true">＋</span><h2>还没有项目</h2><p>点击「新建项目」，为你的下一条作品留一个空间。</p><p className="muted">源文件保留在本地，所有剪辑都可以审阅。</p></div> : <div className="project-grid">{projects.map(project => <article className="project-card" key={project.project_id}><h2>{project.name ?? project.project_id}</h2><p>{project.asset_count} 个素材</p><button aria-label={`进入${project.name ?? project.project_id}`} onClick={() => onSelect(project.project_id)}>进入项目</button><button disabled={deleting !== null} aria-label={`删除${project.name ?? project.project_id}`} onClick={async () => {
      if (!window.confirm(`永久删除“${project.name ?? project.project_id}”？项目内素材副本、转录、作品和导出将被删除，无法撤销。项目外原视频及共享模型缓存保留。`)) return;
      setDeleting(project.project_id); setDeleteError("");
      try { await deleteProject(project.project_id); setProjects(current => current?.filter(p => p.project_id !== project.project_id) ?? null); }
      catch (reason) { setDeleteError(reason instanceof Error ? reason.message : "删除失败"); }
      finally { setDeleting(null); }
    }}>{deleting === project.project_id ? "正在删除…" : "删除项目"}</button></article>)}</div>}
    {creating && <div className="dialog-backdrop"><section onKeyDown={dialogKey} role="dialog" aria-modal="true" aria-labelledby="create-project-title" className="create-dialog"><h2 id="create-project-title">新建项目</h2><form onSubmit={submit}><label htmlFor="project-name">项目名称</label><input id="project-name" autoFocus maxLength={120} value={name} onChange={event => setName(event.target.value)} disabled={saving} required />{createError && <p role="alert">{createError}</p>}<div className="dialog-actions"><button type="button" disabled={saving} onClick={closeDialog}>取消</button><button className="primary-button" disabled={saving || !name.trim()}>{saving ? "正在创建…" : "创建并进入"}</button></div></form></section></div>}
  </section>;
}
