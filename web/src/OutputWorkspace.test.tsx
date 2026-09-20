import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { OutputWorkspace } from "./OutputWorkspace";
vi.mock("./api", async original => ({...await original<typeof import("./api")>(), getHighlights: vi.fn().mockResolvedValue({asset_id:"source",outputs:[{output_id:"video-1",title:"作品A",reason:"理由A",revision:1,clips:[]},{output_id:"video-2",title:"作品B",reason:"理由B",revision:2,clips:[]}]})}));
it("独立作品入口只显示指定计划，不串其他作品", async () => {
  const view = render(<OutputWorkspace project="demo" collection="one" output="video-1" />);
  expect(await screen.findByRole("heading",{name:"作品A"})).toBeInTheDocument();
  view.rerender(<OutputWorkspace key="video-2" project="demo" collection="one" output="video-2" />);
  expect(await screen.findByRole("heading",{name:"作品B"})).toBeInTheDocument();
  expect(screen.queryByRole("heading",{name:"作品A"})).not.toBeInTheDocument();
});

it("范围草稿撤销与批量保存不调用渲染，显式生成才启动",async()=>{
  const api=await import("./api");
  const preview=vi.spyOn(api,"startOutputPreview").mockResolvedValue({task_id:"p",status:"pending",result:null,error:null});
  vi.spyOn(api,"recoverOutputPreview").mockResolvedValue(null);
  const clip={instance_id:"i",segment_id:"s",role:"body" as const,text:"A",start_ms:2000,end_ms:8000};
  const data={asset_id:"a",collection_id:"c",source_duration_ms:20000,notes:[],brief:{preset:"podcast_highlights",count:1,min_ms:null,max_ms:null,hook_ms:null,instructions:"",max_source_overlap:1},outputs:[{output_id:"o",title:"草稿",reason:"完整",revision:1,duration_ms:6000,clips:[clip]}]};
  vi.mocked(api.getHighlights).mockResolvedValue(data);
  const save=vi.spyOn(api,"saveOutputRanges").mockResolvedValue({...data,outputs:[{...data.outputs[0],revision:2,clips:[{...clip,start_ms:2500}]}]});
  render(<OutputWorkspace project="p" collection="c" output="o" />);
  await screen.findByLabelText("快速预览 · 草稿");
  const {fireEvent}=await import("@testing-library/react");
  fireEvent.click(screen.getByLabelText("编辑字幕 i"));
  fireEvent.click(screen.getByText("开始 ＋"));expect(screen.getByLabelText("开始 i")).toHaveValue(2.5);
  fireEvent.click(screen.getByText("撤销"));expect(screen.getByLabelText("开始 i")).toHaveValue(2);
  fireEvent.click(screen.getByText("重做"));expect(screen.getByLabelText("开始 i")).toHaveValue(2.5);
  expect(screen.getByText("生成成片预览")).toBeDisabled();
  fireEvent.click(screen.getByText("保存修改"));
  const {waitFor}=await import("@testing-library/react");
  await waitFor(()=>expect(save).toHaveBeenCalledWith("p","c","o",1,[{instance_id:"i",source_start_ms:2500,source_end_ms:8000}]));
  await waitFor(()=>expect(screen.getByText("生成成片预览")).toBeEnabled());
  expect(preview).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("生成成片预览"));await waitFor(()=>expect(preview).toHaveBeenCalledOnce());
});
