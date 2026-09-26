import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OutputExport } from "./OutputExport";
vi.mock("./api", () => ({recoverOutputExport: vi.fn().mockResolvedValue(null), startOutputExport: vi.fn().mockRejectedValue(new Error("导出失败")), readOutputExport: vi.fn(), cancelOutputExport: vi.fn()}));
it("音频处理默认关闭，失败不显示下载", async () => {
  render(<OutputExport project="p" collection="c" output="o" revision={1} />);
  expect(screen.getByLabelText("降噪")).toHaveValue("none");
  expect(screen.getByLabelText("切点淡入淡出（毫秒）")).toHaveValue(0);
  await userEvent.click(screen.getByRole("button", {name:"导出当前作品"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("导出失败");
  expect(screen.queryByRole("link", {name:"下载视频"})).not.toBeInTheDocument();
});
it("恢复失败后可重新查询，不在恢复期间提交重复导出", async () => {
  const api=await import("./api");
  vi.mocked(api.recoverOutputExport).mockRejectedValueOnce(new Error("暂时离线")).mockResolvedValueOnce({task_id:"done",status:"succeeded",result:{revision:1,output_id:"o",media_url:"/result.mp4",subtitle_url:"/result.srt",duration_ms:1000},error:null});
  render(<OutputExport project="p" collection="c" output="o" revision={1} />);
  expect(screen.getByRole("button",{name:"导出当前作品"})).toBeDisabled();
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时离线");
  await userEvent.click(screen.getByRole("button",{name:"恢复导出状态"}));
  expect(await screen.findByRole("link",{name:"下载视频"})).toHaveAttribute("href","/result.mp4");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
it("提交成功后把作品和任务交给结果页导航",async()=>{
  const api=await import("./api");
  vi.mocked(api.recoverOutputExport).mockResolvedValueOnce(null);
  vi.mocked(api.startOutputExport).mockResolvedValueOnce({task_id:"export-1",status:"pending",result:null,error:null});
  const onSubmitted=vi.fn();
  render(<OutputExport project="p" collection="c" output="o" revision={1} onSubmitted={onSubmitted} />);
  await userEvent.click(await screen.findByRole("button",{name:"导出当前作品"}));
  expect(onSubmitted).toHaveBeenCalledWith([{outputId:"o",taskId:"export-1"}]);
});
