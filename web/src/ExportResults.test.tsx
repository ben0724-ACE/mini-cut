import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ExportResults } from "./ExportResults";
import { resumeTask } from "./api";

vi.mock("./api",()=>({
  getHighlights:vi.fn().mockResolvedValue({outputs:[
    {output_id:"a",title:"作品 A",social_copy:"A 的发布简介",reason:"",revision:1,duration_ms:1000,clips:[]},
    {output_id:"b",title:"作品 B",social_copy:null,reason:"",revision:1,duration_ms:1000,clips:[]},
  ]}),
  readOutputExport:vi.fn().mockImplementation((_project:string,task:string)=>Promise.resolve(task==="task-a"?{
    task_id:task,status:"succeeded",resumable:true,error:null,result:{output_id:"a",revision:1,duration_ms:1000,title:"导出标题 A",social_copy:"导出时保存的简介",media_url:"/a.mp4",cover_url:"/a.jpg",subtitle_url:"/a.srt"},
  }:{task_id:task,status:"failed",resumable:true,error:"渲染失败",result:null})),
  resumeTask:vi.fn().mockResolvedValue({task_id:"task-b-resumed",status:"pending",resumable:true,error:null,result:null}),
  cancelOutputExport:vi.fn(),
}));

it("并列展示导出包，并允许失败任务按原设置恢复",async()=>{
  window.history.replaceState({},"","/?project=p&view=exports&collection=c&output=a&task=task-a&output=b&task=task-b");
  render(<ExportResults project="p" collection="c" entries={[{outputId:"a",taskId:"task-a"},{outputId:"b",taskId:"task-b"}]} />);
  expect(await screen.findByRole("link",{name:"下载视频"})).toHaveAttribute("href","/a.mp4");
  expect(screen.getByRole("link",{name:"下载封面"})).toHaveAttribute("href","/a.jpg");
  expect(screen.getByText("导出时保存的简介")).toBeInTheDocument();
  expect(screen.getByText("旧项目未生成发布文案；不会自动调用 AI 补写。")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"按原设置重新导出"}));
  expect(resumeTask).toHaveBeenCalledWith("p","task-b");
  expect(window.location.search).toContain("task-b-resumed");
});
