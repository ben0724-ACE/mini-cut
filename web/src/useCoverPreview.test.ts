import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {act,renderHook} from "@testing-library/react";
import {useCoverPreview} from "./useCoverPreview";
import {previewCover,type CoverDesign} from "./coverApi";

vi.mock("./coverApi",()=>({previewCover:vi.fn()}));
const design:CoverDesign={mode:"design",aspect_ratio:"9:16",background_color:"#172033",background_image:null,background_scale:1,background_x:.5,background_y:.5,frame_ms:1000,frame:{x:.08,y:.14,width:.84,height:.46},frame_fit:"contain",title:"标题",title_box:{x:.08,y:.66,width:.84,height:.25},font_id:null,font_size:88,bold:true,text_color:"#ffffff",stroke_color:"#000000",stroke_width:0,align:"center"};
const preview=(label:string)=>({blob:new Blob([label]),warnings:[]});
const tick=async(ms:number)=>{await act(()=>vi.advanceTimersByTimeAsync(ms));};
beforeEach(()=>{
  vi.useFakeTimers();vi.clearAllMocks();
  vi.mocked(previewCover).mockResolvedValue(preview("frame"));
  let count=0;URL.createObjectURL=vi.fn(()=>`blob:frame-${++count}`);URL.revokeObjectURL=vi.fn();
});
afterEach(()=>vi.useRealTimers());

it("连续拖动每隔 250ms 更新最新帧，不等待用户停止输入",async()=>{
  const {result,rerender}=renderHook(({draft})=>useCoverPreview("/cover",1,draft),{initialProps:{draft:design}});
  await tick(0);expect(result.current.image).toBe("blob:frame-1");
  for(const [time,frame] of [[100,1100],[100,1200],[60,1300]]){
    rerender({draft:{...design,frame_ms:frame}});await tick(time!);
  }
  expect(previewCover).toHaveBeenCalledTimes(2);
  expect(previewCover).toHaveBeenLastCalledWith("/cover",1,expect.objectContaining({frame_ms:1300}),expect.any(AbortSignal));
  expect(result.current.image).toBe("blob:frame-2");
  rerender({draft:{...design,frame_ms:1400}});await tick(240);
  expect(previewCover).toHaveBeenCalledTimes(3);expect(result.current.rendering).toBe(false);
});

it("慢预览只保留一个在途请求，显示中间结果并最终渲染最新选择",async()=>{
  let finish!:(value:ReturnType<typeof preview>)=>void;
  vi.mocked(previewCover).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  const {result,rerender}=renderHook(({draft})=>useCoverPreview("/cover",1,draft),{initialProps:{draft:design}});
  await tick(0);
  rerender({draft:{...design,frame_ms:1200}});await tick(300);
  rerender({draft:{...design,frame_ms:1800}});await tick(300);
  expect(previewCover).toHaveBeenCalledTimes(1);
  expect(vi.mocked(previewCover).mock.calls[0]![3]!.aborted).toBe(false);
  await act(async()=>finish(preview("first")));
  expect(result.current.image).toBe("blob:frame-1");expect(result.current.rendering).toBe(true);
  await tick(0);
  expect(previewCover).toHaveBeenCalledTimes(2);
  expect(previewCover).toHaveBeenLastCalledWith("/cover",1,expect.objectContaining({frame_ms:1800}),expect.any(AbortSignal));
  expect(result.current.image).toBe("blob:frame-2");expect(result.current.rendering).toBe(false);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:frame-1");
});

it("切换作品版本时取消旧请求，旧结果不会覆盖新预览，卸载释放图片",async()=>{
  let finish!:(value:ReturnType<typeof preview>)=>void;
  vi.mocked(previewCover).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  const {result,rerender,unmount}=renderHook(({revision})=>useCoverPreview("/cover",revision,design),{initialProps:{revision:1}});
  await tick(0);const oldSignal=vi.mocked(previewCover).mock.calls[0]![3]!;
  rerender({revision:2});await tick(0);
  expect(oldSignal.aborted).toBe(true);expect(result.current.image).toBe("blob:frame-1");
  await act(async()=>finish(preview("old")));
  expect(URL.createObjectURL).toHaveBeenCalledTimes(1);expect(result.current.image).toBe("blob:frame-1");
  unmount();expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:frame-1");
});

it("预览失败后保留已显示画面，后续编辑可以恢复；第一帧模式不请求预览",async()=>{
  const {result,rerender}=renderHook(({draft})=>useCoverPreview("/cover",1,draft),{initialProps:{draft:design}});
  await tick(0);vi.mocked(previewCover).mockRejectedValueOnce(new Error("预览失败"));
  rerender({draft:{...design,frame_ms:1500}});await tick(250);
  expect(result.current.error).toBe("预览失败");expect(result.current.image).toBe("blob:frame-1");expect(result.current.rendering).toBe(false);
  rerender({draft:{...design,frame_ms:1800}});await tick(250);
  expect(result.current.error).toBe("");expect(result.current.image).toBe("blob:frame-2");
  rerender({draft:{...design,mode:"first_frame"}});await tick(500);
  expect(previewCover).toHaveBeenCalledTimes(3);expect(result.current.image).toBe("");
});
