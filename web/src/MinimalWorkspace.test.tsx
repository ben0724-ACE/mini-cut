import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {act,render,screen,waitFor,within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {MinimalWorkspace} from "./MinimalWorkspace";
import {defaultGenerationDraft} from "./generationDraft";
import {defaultExportOptions} from "./exportSettingsApi";
import * as api from "./api";
import * as workflows from "./workflowApi";

vi.mock("./api",async original=>({...await original<typeof import("./api")>(),listAssets:vi.fn(),uploadAsset:vi.fn(),recoverHighlights:vi.fn(),recoverOutputExport:vi.fn(),getHighlights:vi.fn(),saveHighlightSelection:vi.fn(),startOutputExportBatch:vi.fn(),readHighlightTask:vi.fn()}));
vi.mock("./workflowApi",async original=>({...await original<typeof import("./workflowApi")>(),listWorkflows:vi.fn(),latestWorkflowRun:vi.fn(),startWorkflowRun:vi.fn(),workflowAction:vi.fn()}));
vi.mock("./QuickPreview",()=>({QuickPreview:({title}:{title:string})=><div>试听 {title}</div>}));
vi.mock("./WorkflowManager",()=>({WorkflowManager:()=> <div>管理我的工作流</div>}));
const workflow:workflows.Workflow={workflow_id:"podcast",name:"AI 播客",generation:defaultGenerationDraft(),transcription:{provider:"mlx",model:"large-v3-turbo",language:"en"},export_options:defaultExportOptions(),layout:{},auto_export:false,cover_template_id:null,created_at:"",updated_at:""};
const result:api.HighlightResult={collection_id:"c",asset_id:"a",brief:{preset:"podcast_highlights",count:1,min_ms:1000,max_ms:2000,hook_ms:null,max_source_overlap:1},notes:[],outputs:[{output_id:"o",title:"AI 的未来",reason:"主题完整",revision:2,duration_ms:1800,clips:[]}],selected_output_ids:["o"]};
const completed:workflows.WorkflowRun={task_id:"run",asset_id:"a",workflow_name:"AI 播客",status:"succeeded",phase:"completed",error:null,result,exports:[],child_task_ids:[]};
beforeEach(()=>{vi.clearAllMocks();localStorage.clear();vi.mocked(workflows.listWorkflows).mockResolvedValue([workflow]);vi.mocked(workflows.latestWorkflowRun).mockResolvedValue(null);vi.mocked(api.listAssets).mockResolvedValue([]);vi.mocked(api.getHighlights).mockResolvedValue(result);vi.mocked(api.recoverHighlights).mockResolvedValue(null);vi.mocked(api.recoverOutputExport).mockResolvedValue(null);});
afterEach(()=>{localStorage.clear();window.history.replaceState({},"","/");});
it("选择视频并点击一次就上传和启动工作流，快速重复点击只提交一次",async()=>{
  const user=userEvent.setup();vi.mocked(api.uploadAsset).mockResolvedValue({asset_id:"a"});vi.mocked(workflows.startWorkflowRun).mockResolvedValue({...completed,status:"pending",result:null,phase:"pending"});
  render(<MinimalWorkspace project="p" onRefine={vi.fn()}/>);
  const button=await screen.findByRole("button",{name:"一键生成"});await waitFor(()=>expect(screen.getByRole("combobox",{name:"工作流"})).toBeEnabled());
  await user.upload(screen.getByLabelText("上传视频"),new File(["video"],"podcast.mp4",{type:"video/mp4"}));await user.dblClick(button);
  await waitFor(()=>expect(workflows.startWorkflowRun).toHaveBeenCalledTimes(1));
  expect(api.uploadAsset).toHaveBeenCalledTimes(1);expect(workflows.startWorkflowRun).toHaveBeenCalledWith("p","a","podcast",expect.any(String));
  expect(screen.getByRole("button",{name:"取消工作流"})).toBeInTheDocument();expect(screen.queryByLabelText("剪辑提示词")).not.toBeInTheDocument();
});
it("恢复已完成任务、预览和精修，进入页面不会启动模型任务",async()=>{
  vi.mocked(workflows.latestWorkflowRun).mockResolvedValue(completed);vi.mocked(api.listAssets).mockResolvedValue([{asset_id:"a",name:"podcast.mp4",duration_ms:5000,has_transcript:true,has_plan:false}]);const refine=vi.fn();const user=userEvent.setup();
  render(<MinimalWorkspace project="p" onRefine={refine}/>);
  expect(await screen.findByRole("region",{name:"极简模式结果"})).toBeInTheDocument();expect(screen.getByText("试听 AI 的未来")).toBeInTheDocument();
  await user.click(screen.getByRole("button",{name:"精修"}));expect(refine).toHaveBeenCalledWith("c","o");expect(workflows.startWorkflowRun).not.toHaveBeenCalled();
});
it("生成详情点击一次直接展示内容，关闭弹窗后恢复焦点",async()=>{
  vi.mocked(workflows.latestWorkflowRun).mockResolvedValue(completed);vi.mocked(api.listAssets).mockResolvedValue([{asset_id:"a",name:"podcast.mp4",duration_ms:5000,has_transcript:true,has_plan:false}]);const user=userEvent.setup();
  render(<MinimalWorkspace project="p" onRefine={vi.fn()}/>);
  const trigger=await screen.findByRole("button",{name:"生成详情"});await user.click(trigger);
  const dialog=screen.getByRole("dialog",{name:"生成详情"});
  expect(within(dialog).getByText(/源素材：podcast.mp4/)).toBeVisible();
  expect(within(dialog).getByText(/已生成 1 \/ 1 条候选/)).toBeVisible();
  expect(dialog.querySelector("summary")).toBeNull();
  await user.keyboard("{Escape}");expect(screen.queryByRole("dialog")).not.toBeInTheDocument();expect(trigger).toHaveFocus();
});
it("没有工作流运行记录也可恢复手动导出，一次点击进入现有结果页",async()=>{
  const user=userEvent.setup();
  vi.mocked(api.listAssets).mockResolvedValue([{asset_id:"a",name:"podcast.mp4",duration_ms:5000,has_transcript:true,has_plan:false}]);
  vi.mocked(api.recoverHighlights).mockResolvedValue({task_id:"generation",status:"succeeded",error:null,result});
  const outputs=[...result.outputs,{...result.outputs[0],output_id:"other",title:"另一个话题"}];
  vi.mocked(api.getHighlights).mockResolvedValue({...result,outputs});
  vi.mocked(api.recoverOutputExport).mockImplementation(async(_project,_collection,output)=>({task_id:`export-${output}`,status:output==="o"?"succeeded":"running",error:null,result:null}));
  render(<MinimalWorkspace project="p" onRefine={vi.fn()}/>);
  await user.click(await screen.findByRole("button",{name:"查看导出结果"}));
  const query=new URLSearchParams(window.location.search);
  expect(query.get("view")).toBe("exports");expect(query.get("project")).toBe("p");expect(query.get("collection")).toBe("c");
  expect(query.getAll("output")).toEqual(["o","other"]);expect(query.getAll("task")).toEqual(["export-o","export-other"]);
  expect(workflows.startWorkflowRun).not.toHaveBeenCalled();expect(api.startOutputExportBatch).not.toHaveBeenCalled();
});
it("没有导出记录时不显示入口，自动导出记录也只显示一个入口",async()=>{
  vi.mocked(workflows.latestWorkflowRun).mockResolvedValue(completed);
  const view=render(<MinimalWorkspace project="p" onRefine={vi.fn()}/>);
  await screen.findByRole("region",{name:"极简模式结果"});await waitFor(()=>expect(api.recoverOutputExport).toHaveBeenCalledWith("p","c","o",expect.any(AbortSignal)));
  expect(screen.queryByRole("button",{name:"查看导出结果"})).not.toBeInTheDocument();
  view.unmount();
  vi.mocked(workflows.latestWorkflowRun).mockResolvedValue({...completed,exports:[{outputId:"o",taskId:"auto-export"}]});
  vi.mocked(api.recoverOutputExport).mockResolvedValue({task_id:"auto-export",status:"succeeded",error:null,result:null});
  render(<MinimalWorkspace project="p" onRefine={vi.fn()}/>);
  await screen.findByRole("button",{name:"查看导出结果"});expect(screen.getAllByRole("button",{name:"查看导出结果"})).toHaveLength(1);
});
it("切换素材后导出入口对应新素材的集合与任务",async()=>{
  const user=userEvent.setup();const otherResult={...result,collection_id:"new-collection",asset_id:"b"};
  vi.mocked(api.listAssets).mockResolvedValue(["a","b"].map(asset_id=>({asset_id,name:`${asset_id}.mp4`,duration_ms:5000,has_transcript:true,has_plan:false})));
  vi.mocked(api.recoverHighlights).mockImplementation(async(_project,asset)=>({task_id:`generation-${asset}`,status:"succeeded",error:null,result:asset==="a"?result:otherResult}));
  vi.mocked(api.getHighlights).mockImplementation(async(_project,collection)=>collection==="c"?result:otherResult);
  vi.mocked(api.recoverOutputExport).mockImplementation(async(_project,collection)=>({task_id:`export-${collection}`,status:"succeeded",error:null,result:null}));
  render(<MinimalWorkspace project="p" onRefine={vi.fn()}/>);
  await screen.findByRole("button",{name:"查看导出结果"});await waitFor(()=>expect(screen.getByRole("combobox",{name:"极简模式素材"})).toBeEnabled());
  await user.selectOptions(screen.getByRole("combobox",{name:"极简模式素材"}),"b");
  await user.click(await screen.findByRole("button",{name:"查看导出结果"}));
  const query=new URLSearchParams(window.location.search);expect(query.get("collection")).toBe("new-collection");expect(query.get("task")).toBe("export-new-collection");
});
it("自动导出任务稍后产生时也显示结果入口",async()=>{
  vi.useFakeTimers();
  try{
    vi.mocked(workflows.latestWorkflowRun).mockResolvedValueOnce({...completed,status:"running",phase:"export"}).mockResolvedValue({...completed,exports:[{outputId:"o",taskId:"auto-export"}]});
    await act(async()=>{render(<MinimalWorkspace project="p" onRefine={vi.fn()}/>);});
    expect(screen.queryByRole("button",{name:"查看导出结果"})).not.toBeInTheDocument();
    await act(async()=>{await vi.advanceTimersByTimeAsync(1500);});
    expect(screen.getByRole("button",{name:"查看导出结果"})).toBeInTheDocument();
    expect(api.recoverOutputExport).toHaveBeenCalledTimes(2);
  }finally{vi.useRealTimers();}
});
it("失败后提供继续工作流，使用同一个运行记录",async()=>{
  vi.mocked(workflows.latestWorkflowRun).mockResolvedValue({...completed,status:"failed",error:"模型暂时不可用",result:null});vi.mocked(workflows.workflowAction).mockResolvedValue({...completed,status:"pending",phase:"pending",result:null});const user=userEvent.setup();
  render(<MinimalWorkspace project="p" onRefine={vi.fn()}/>);await user.click(await screen.findByRole("button",{name:"继续工作流"}));
  expect(workflows.workflowAction).toHaveBeenCalledWith("p","run","resume");expect(workflows.startWorkflowRun).not.toHaveBeenCalled();
});
it("已上传素材在提交请求失败后复用，重试使用相同请求标识",async()=>{
  vi.mocked(api.uploadAsset).mockResolvedValue({asset_id:"a"});vi.mocked(workflows.startWorkflowRun).mockRejectedValueOnce(new Error("网络中断")).mockResolvedValue({...completed,status:"pending",phase:"pending",result:null});const user=userEvent.setup();
  render(<MinimalWorkspace project="p" onRefine={vi.fn()}/>);await waitFor(()=>expect(screen.getByRole("combobox",{name:"工作流"})).toBeEnabled());await user.upload(screen.getByLabelText("上传视频"),new File(["video"],"podcast.mp4",{type:"video/mp4"}));
  await user.click(screen.getByRole("button",{name:"一键生成"}));expect(await screen.findByRole("alert")).toHaveTextContent("网络中断");await user.click(screen.getByRole("button",{name:"一键生成"}));
  await waitFor(()=>expect(workflows.startWorkflowRun).toHaveBeenCalledTimes(2));expect(api.uploadAsset).toHaveBeenCalledTimes(1);expect(vi.mocked(workflows.startWorkflowRun).mock.calls[0][3]).toBe(vi.mocked(workflows.startWorkflowRun).mock.calls[1][3]);
});
