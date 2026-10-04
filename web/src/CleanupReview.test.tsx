import {render,screen,waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {it,expect,vi} from "vitest";
import {CleanupReview} from "./CleanupReview";
import {renameOutput,type HighlightOutput,type HighlightResult} from "./api";
vi.mock("./api",async original=>({...await original<typeof import("./api")>(),renameOutput:vi.fn()}));
const plan:HighlightOutput={output_id:"cleanup",title:"素材 · 清理版",workflow:"speech_cleanup",reason:"",revision:1,duration_ms:3000,clips:[{instance_id:"cut",segment_id:"s",role:"body",text:"呃",deleted:true,cleanup_category:"填充词",start_ms:1000,end_ms:1200}]};
it("审阅删除、恢复及手动命名，不要求发布文案",async()=>{
  const restore=vi.fn().mockResolvedValue(undefined),updated=vi.fn();
  vi.mocked(renameOutput).mockResolvedValue({outputs:[{...plan,title:"新名字"}]} as HighlightResult);
  render(<CleanupReview project="p" collection="c" plan={plan} sourceUrl="/source" sourceDuration={3200} disabled={false} onRestore={restore} onUpdated={updated}/>);
  expect(screen.getByText(/此流程不生成文案/)).toBeInTheDocument();
  await userEvent.click(screen.getByText("查看删除清单与切点试听"));
  expect(screen.getByText(/填充词 · 1.00–1.20/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"恢复此处"}));
  expect(restore).toHaveBeenCalledWith("cut");
  await userEvent.clear(screen.getByLabelText("作品名"));await userEvent.type(screen.getByLabelText("作品名"),"新名字");
  await userEvent.click(screen.getByRole("button",{name:"保存作品名"}));
  await waitFor(()=>expect(renameOutput).toHaveBeenCalledWith("p","c","cleanup",1,"新名字"));
  expect(updated).toHaveBeenCalled();
});

it("点击就试听，在清单前显示播放器，重复点击会重新播放",async()=>{
  const play=vi.spyOn(HTMLMediaElement.prototype,"play").mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype,"readyState","get").mockReturnValue(1);
  vi.spyOn(HTMLMediaElement.prototype,"pause").mockImplementation(()=>{});
  const clips=[{...plan.clips[0],instance_id:"before",deleted:false,start_ms:0,end_ms:1000},plan.clips[0],{...plan.clips[0],instance_id:"after",deleted:false,start_ms:1200,end_ms:3200}];
  render(<CleanupReview project="p" collection="c" plan={{...plan,clips}} sourceUrl="/source" sourceDuration={3200} disabled={false} onRestore={vi.fn()} onUpdated={vi.fn()}/>);
  await userEvent.click(screen.getByText("查看删除清单与切点试听"));
  await userEvent.click(screen.getByRole("button",{name:"试听清理后切点"}));
  const video=screen.getByLabelText("快速预览 · 清理切点试听") as HTMLVideoElement;
  expect(play).toHaveBeenCalledTimes(1);
  expect(video.currentTime).toBe(0);
  video.currentTime=1;
  const {fireEvent}=await import("@testing-library/react");
  fireEvent.timeUpdate(video);
  expect(video.currentTime).toBe(1.2);
  expect(screen.getByLabelText("切点试听播放器").compareDocumentPosition(screen.getByRole("button",{name:"试听清理后切点"})) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  await userEvent.click(screen.getByRole("button",{name:"试听清理后切点"}));
  expect(play).toHaveBeenCalledTimes(2);
  expect(video.currentTime).toBe(0);
  await userEvent.click(screen.getByRole("button",{name:"试听原片上下文"}));
  video.currentTime=1;
  fireEvent.timeUpdate(video);
  expect(video.currentTime).toBe(1);
});

it("大清单分页，避免播放器藏在数百条记录后",async()=>{
  const clips=Array.from({length:162},(_,i)=>({...plan.clips[0],instance_id:String(i),start_ms:i*1000,end_ms:i*1000+100}));
  render(<CleanupReview project="p" collection="c" plan={{...plan,clips}} sourceUrl="/source" sourceDuration={200000} disabled={false} onRestore={vi.fn()} onUpdated={vi.fn()}/>);
  await userEvent.click(screen.getByText("查看删除清单与切点试听"));
  expect(screen.getAllByRole("button",{name:"恢复此处"})).toHaveLength(20);
  await userEvent.click(screen.getByRole("button",{name:"下一页"}));
  expect(screen.getByText(/第 2 \/ 9 页/)).toBeInTheDocument();
  expect(screen.getByText(/填充词 · 20.00–20.10/)).toBeInTheDocument();
});
