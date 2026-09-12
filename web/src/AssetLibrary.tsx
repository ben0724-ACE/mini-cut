import { useEffect, useState } from "react";
import { listAssets, uploadAsset, type AssetDetail } from "./api";

interface Props {
  projectId: string;
  onOpen: (asset: string) => void;
  load?: typeof listAssets;
  upload?: typeof uploadAsset;
}
export function AssetLibrary({projectId, onOpen, load = listAssets, upload = uploadAsset}: Props) {
  const [assets, setAssets] = useState<AssetDetail[] | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    load(projectId, controller.signal).then(value => { if (!controller.signal.aborted) setAssets(value); }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "无法读取素材"); });
    return () => controller.abort();
  }, [projectId, load, retry]);
  async function submit() {
    if (!file || busy) return;
    setBusy(true); setError("");
    try { await upload(projectId, file); setAssets(await load(projectId)); }
    catch (reason: unknown) { setError(reason instanceof Error ? reason.message : "导入失败"); }
    finally { setBusy(false); }
  }
  return <section aria-label="素材库">
    <h2>素材{assets !== null && `（${assets.length}）`}</h2>
    <p>选择文件会复制到本地项目；不会修改原媒体，也不会上传到大语言模型。已有画面字幕无法在导入时自动识别或去除。</p>
    <label htmlFor="media-file">选择媒体文件</label>{" "}
    <input id="media-file" type="file" accept=".mp4,.mov,.mkv,.avi,.flv,.f4v,.webm,.ogg,.wav,.mp3,.flac,.m4a" disabled={busy} onChange={event => setFile(event.target.files?.[0] ?? null)} />
    <button disabled={!file || busy} onClick={submit}>{busy ? "正在导入并读取媒体…" : "导入素材"}</button>
    {busy && <p role="status">请等待文件传输和媒体分析完成。</p>}
    {error && <div><p role="alert">{error}</p><button disabled={busy} onClick={() => {setError(""); setRetry(value => value + 1);}}>重新读取列表</button></div>}
    {assets === null ? <p role="status">正在读取素材…</p> : assets.length === 0 ? <p>尚无素材</p> : <div className="project-grid">{assets.map(asset => <article className="project-card" key={asset.asset_id}><h3>{asset.name}</h3><p>{(asset.duration_ms / 1000).toFixed(2)} 秒 · {asset.has_transcript ? "已转录" : "未转录"}</p>{asset.has_plan && <button onClick={() => onOpen(asset.asset_id)}>审阅现有剪辑</button>}</article>)}</div>}
    <p>Web 转录控制将在下一闭环接通。</p>
  </section>;
}
