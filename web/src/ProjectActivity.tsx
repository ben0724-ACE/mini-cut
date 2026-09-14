import {useEffect,useState} from 'react';
import type {ModelReceipt} from './api';
import {ModelUsage} from './ModelUsage';
interface Activity {heavy_task_concurrency:number;model_requests:ModelReceipt[];tasks:{task_id:string;kind:string;status:string;error?:string;progress?:{completed?:number;total?:number}}[]}
const kindText:Record<string,string>={'transcribe':'转录','highlights':'AI 生成','output-preview':'成片预览','output-export':'作品导出'};
const statusText:Record<string,string>={pending:'等待执行',running:'运行中',succeeded:'已完成',failed:'失败 / 已中断',cancelled:'已取消'};
export function ProjectActivity({project}:{project:string}) {
  const [open,setOpen]=useState(false),[data,setData]=useState<Activity|null>(null),[error,setError]=useState('');
  useEffect(()=>{if(!open)return;const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
    async function load(){try{const response=await fetch(`/api/projects/${encodeURIComponent(project)}/activity`,{signal:controller.signal});if(!response.ok)throw new Error('无法读取项目任务');const value=await response.json() as Activity;if(!controller.signal.aborted){setData(value);setError('');}}catch(reason){if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:'读取失败');}finally{if(!controller.signal.aborted)timer=setTimeout(()=>void load(),5000);}}
    void load();return()=>{controller.abort();clearTimeout(timer);};},[project,open]);
  return <details className="project-activity" onToggle={event=>setOpen(event.currentTarget.open)}><summary>项目任务与 AI 用量</summary>{error&&<p role="alert">{error}</p>}{data?<><p className="helper-text">转录与渲染等重任务最多同时执行 {data.heavy_task_concurrency} 个；刷新不会丢失已保存的阶段。显示最近 20 个任务和 100 次模型请求。</p><ModelUsage requests={data.model_requests} ledger /><ul>{data.tasks.map(task=><li key={task.task_id}>{kindText[task.kind]??task.kind} · {statusText[task.status]??task.status}{task.progress?.total!=null&&` · ${task.progress.completed}/${task.progress.total}`}{task.error&&<p className="helper-text">{task.error}</p>}</li>)}</ul></>:<p role="status">正在读取项目活动…</p>}</details>;
}
