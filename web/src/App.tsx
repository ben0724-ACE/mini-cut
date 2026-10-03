import { navigateWithDraft } from "./draftNavigation";
import { useEffect, useState } from "react";
import {
  ApiError,
  getPlan,
  getProject,
  listProjects,
  createProject,
  getPreviewTimeline,
  modifyPlan,
  renderAndWait,
  type PlanDetail,
  type PreviewTimeline,
  type ProjectDetail,
} from "./api";
import { PlanReview } from "./PlanReview";
import { ProjectHome } from "./ProjectHome";
import { AssetLibrary } from "./AssetLibrary";
import { OutputWorkspace } from "./OutputWorkspace";
import { ExportResults } from "./ExportResults";
import { navigateToExportResults } from "./exportNavigation";
import { MinimalWorkspace } from "./MinimalWorkspace";
import {readMode,saveMode,type WorkspaceMode} from "./workflowApi";

export function App() {
  const [search, setSearch] = useState(window.location.search);
  useEffect(() => {
    const update = () => setSearch(window.location.search);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  const parameters = new URLSearchParams(search);
  const projectId = parameters.get("project") ?? "";
  const [mode,setMode]=useState<WorkspaceMode>(()=>readMode(projectId));
  useEffect(()=>setMode(readMode(projectId)),[projectId]);
  const assetId = parameters.get("asset") ?? "";
  const collectionId = parameters.get("collection") ?? "";
  const outputId = parameters.get("output") ?? "";
  const exportEntries=parameters.getAll("output").map((outputId,index)=>({outputId,taskId:parameters.getAll("task")[index]??""})).filter(entry=>entry.outputId&&entry.taskId);
  function navigate(project = "", asset = "") {
    navigateWithDraft(()=>{
    const query = new URLSearchParams();
    if (project) query.set("project", project);
    if (asset) query.set("asset", asset);
    window.history.pushState({}, "", `${window.location.pathname}${query.size ? `?${query}` : ""}`);
    setSearch(window.location.search);
    });
  }
  function switchMode(next:WorkspaceMode,collection="",output="") {
    navigateWithDraft(()=>{
      saveMode(next,projectId);setMode(next);
      const query=new URLSearchParams({project:projectId});
      if(collection)query.set("collection",collection);
      if(output)query.set("output",output);
      window.history.pushState({},"",`${window.location.pathname}?${query}`);
      setSearch(window.location.search);
    });
  }
  return <div className="app-frame">
    <a className="skip-link" href="#main-content">跳转到主要内容</a>
    <header className="app-header"><strong className="brand"><span aria-hidden="true" className="brand-mark">M</span>MiniCut</strong><span>本地剪辑工作台</span><span className="local-badge">本地优先</span></header>
    <div className="app-body">
      <nav aria-label="项目导航"><button onClick={() => navigate()}>我的项目</button>
        {projectId && <button onClick={() => navigate(projectId)}>当前项目</button>}
        {projectId && <div className="workspace-mode-switch" aria-label="工作模式"><button aria-pressed={mode==="minimal"} onClick={()=>switchMode("minimal")}>极简模式</button><button aria-pressed={mode==="full"} onClick={()=>switchMode("full")}>完整模式</button></div>}
      </nav>
      <main id="main-content" tabIndex={-1} className="app-content">
        {!projectId ? <ProjectHome loadProjects={listProjects} createProject={createProject} onSelect={(id) => navigate(id)} />
          : parameters.get("view")==="exports"&&collectionId&&exportEntries.length ? <ExportResults project={projectId} collection={collectionId} entries={exportEntries} />
          : collectionId && outputId ? <OutputWorkspace key={`${projectId}:${collectionId}:${outputId}`} project={projectId} collection={collectionId} output={outputId} onExportSubmitted={entries=>navigateToExportResults(projectId,collectionId,entries)} />
          : mode==="minimal" ? <ProjectWorkspace key={`${projectId}:minimal`} projectId={projectId} onOpen={(asset)=>navigate(projectId,asset)} minimal onRefine={(collection,output)=>switchMode("full",collection,output)} />
          : !assetId ? <ProjectWorkspace key={projectId} projectId={projectId} onOpen={(asset) => navigate(projectId, asset)} />
          : <Review key={`${projectId}:${assetId}`} projectId={projectId} assetId={assetId} />}
      </main>
    </div>
  </div>;
}

function ProjectWorkspace({ projectId, onOpen, minimal=false, onRefine }: { projectId: string; onOpen: (asset: string) => void;minimal?:boolean;onRefine?:(collection:string,output:string)=>void }) {
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    getProject(projectId, controller.signal).then((value) => {
      if (!controller.signal.aborted) setProject(value);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "无法读取项目");
    });
    return () => controller.abort();
  }, [projectId]);
  if (error) return <p role="alert">{error}</p>;
  if (!project) return <p role="status">正在读取项目…</p>;
  return <section><header className="workspace-heading"><h1>{project.name ?? project.project_id}</h1></header>
    {minimal ? <MinimalWorkspace project={projectId} onRefine={onRefine!}/> : <AssetLibrary projectId={projectId} onOpen={onOpen} />}
  </section>;
}

function Review({ projectId, assetId }: { projectId: string; assetId: string }) {
  const [plan, setPlan] = useState<PlanDetail | null>(null);
  const [preview, setPreview] = useState<PreviewTimeline | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!projectId || !assetId) return;
    const controller = new AbortController();
    Promise.all([
      getPlan(projectId, assetId, controller.signal),
      getPreviewTimeline(projectId, assetId, controller.signal),
    ])
      .then(([loadedPlan, loadedPreview]) => {
        setPlan(loadedPlan);
        setPreview(loadedPreview);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof ApiError ? reason.message : "无法读取剪辑计划");
      });
    return () => controller.abort();
  }, [projectId, assetId]);

  if (!projectId || !assetId) {
    return <main className="shell"><p role="status">请在地址中提供 project 和 asset 参数。</p></main>;
  }
  if (error) return <main className="shell"><p role="alert">{error}</p></main>;
  if (!plan || !preview) return <main className="shell"><p role="status">正在读取剪辑计划…</p></main>;
  return (
    <main className="shell">
      <PlanReview
        initialPlan={plan}
        initialPreview={preview}
        mediaUrl={`/api/projects/${encodeURIComponent(projectId)}/media/source/${encodeURIComponent(assetId)}`}
        renderVideo={(outputName) => renderAndWait(projectId, assetId, outputName)}
        saveDecision={async (segmentId, action) => {
          const updatedPlan = await modifyPlan(
            projectId,
            assetId,
            segmentId,
            action,
          );
          const updatedPreview = await getPreviewTimeline(projectId, assetId);
          return { plan: updatedPlan, preview: updatedPreview };
        }}
      />
    </main>
  );
}
