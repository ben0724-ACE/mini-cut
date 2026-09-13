import { it,expect,vi } from "vitest";
import { render,screen } from "@testing-library/react";
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
