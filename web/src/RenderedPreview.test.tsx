import { it,expect,vi } from "vitest";
import { fireEvent,render,screen } from "@testing-library/react";
import { RenderedPreview } from "./RenderedPreview";
import { recoverOutputPreview } from "./api";
vi.mock("./api",()=>({recoverOutputPreview:vi.fn().mockResolvedValue({task_id:"p",status:"succeeded",result:{revision:1,media_url:"/cut.mp4",duration_ms:2000},error:null}),startOutputPreview:vi.fn(),readOutputExport:vi.fn()}));
it("直接播放真实成片而非源视频，新版本不展示旧文件",async()=>{
  const view=render(<RenderedPreview project="p" collection="c" output="o" revision={1} title="T" sourceUrl="/source" />);
  expect(await screen.findByLabelText("成片预览 · T")).toHaveAttribute("src","/cut.mp4");
  vi.mocked(recoverOutputPreview).mockResolvedValueOnce({task_id:"new",status:"pending",result:null,error:null});
  view.rerender(<RenderedPreview key="v2" project="p" collection="c" output="o" revision={2} title="T" sourceUrl="/source" />);
  expect(screen.queryByLabelText("成片预览 · T")).not.toBeInTheDocument();
  expect(await screen.findByRole("status")).toHaveTextContent("v2");
});
it("生成失败明确显示错误而不回退成源视频",async()=>{
  vi.mocked(recoverOutputPreview).mockResolvedValueOnce({task_id:"failed",status:"failed",result:null,error:"render failed"});
  render(<RenderedPreview project="p" collection="c" output="o" revision={1} title="Failed" sourceUrl="/source" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("render failed");
  expect(screen.getByRole("button",{name:"重试预览"})).toBeInTheDocument();
  expect(screen.queryByLabelText("成片预览 · Failed")).not.toBeInTheDocument();
});
it("源素材定位仍只有一个播放器，返回后从成片起点播放",async()=>{
  const view=render(<RenderedPreview project="p" collection="c" output="o" revision={1} title="Inspect" sourceUrl="/source" />);
  await screen.findByLabelText("成片预览 · Inspect");
  view.rerender(<RenderedPreview project="p" collection="c" output="o" revision={1} title="Inspect" sourceUrl="/source" jumpTo={{ms:12340,sequence:1}} />);
  const source=await screen.findByLabelText("源素材 · Inspect");
  fireEvent.loadedMetadata(source);
  expect((source as HTMLVideoElement).currentTime).toBe(12.34);
  expect(view.container.querySelectorAll("video")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button",{name:"返回成片预览"}));
  const edited=await screen.findByLabelText("成片预览 · Inspect");
  expect(edited).toHaveAttribute("src","/cut.mp4");
  expect((edited as HTMLVideoElement).currentTime).toBe(0);
  expect(view.container.querySelectorAll("video")).toHaveLength(1);
});
