import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AssetLibrary } from "./AssetLibrary";

it("上传所选文件后刷新真实素材列表", async () => {
  const load = vi.fn().mockResolvedValueOnce([]).mockResolvedValue([{asset_id: "one", name: "中文.mov", duration_ms: 22041, has_transcript: false, has_plan: false}]);
  const upload = vi.fn().mockResolvedValue({asset_id: "one"});
  render(<AssetLibrary projectId="demo" load={load} upload={upload} onOpen={vi.fn()} />);
  expect(await screen.findByRole("button", {name: "选择本地文件"})).toBeInTheDocument();
  expect(screen.queryByText("尚无素材")).not.toBeInTheDocument();
  expect(screen.getByRole("button", {name: "导入选中文件"})).toBeDisabled();
  const file = new File(["media"], "中文.mov", {type: "video/quicktime"});
  await userEvent.upload(document.querySelector<HTMLInputElement>(".import-file-input")!, file);
  expect(screen.getByRole("button", {name: "导入选中文件"})).toBeEnabled();
  await userEvent.click(screen.getByRole("button", {name: "导入选中文件"}));
  expect(await screen.findByRole("combobox", {name: "当前素材"})).toHaveValue("one");
  expect(screen.getByRole("option", {name: "中文.mov"})).toBeInTheDocument();
  expect(upload).toHaveBeenCalledWith("demo", file);
  expect(screen.getByText(/未转录/)).toBeInTheDocument();
});
it("上传失败保留文件供重试，不伪造素材", async () => {
  render(<AssetLibrary projectId="demo" load={vi.fn().mockResolvedValue([])} upload={vi.fn().mockRejectedValue(new Error("损坏媒体"))} onOpen={vi.fn()} />);
  await userEvent.upload(document.querySelector<HTMLInputElement>(".import-file-input")!, new File(["bad"], "bad.mov", {type: "video/quicktime"}));
  await userEvent.click(screen.getByRole("button", {name: "导入选中文件"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("损坏媒体");
  expect(screen.getByRole("button", {name: "导入选中文件"})).toBeEnabled();
});
it("已转录素材默认收起转录设置，仍可手动展开", async () => {
  render(<AssetLibrary projectId="demo" load={vi.fn().mockResolvedValue([{asset_id:"one",name:"访谈.mov",duration_ms:60000,has_transcript:true,has_plan:false}])} onOpen={vi.fn()} />);
  const summary=await screen.findByText("转录设置 · 已完成");
  const details=summary.closest("details");
  expect(details).not.toHaveAttribute("open");
  await userEvent.click(summary);
  expect(details).toHaveAttribute("open");
});
