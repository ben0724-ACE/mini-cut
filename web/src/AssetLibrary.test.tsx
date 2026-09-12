import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AssetLibrary } from "./AssetLibrary";

it("上传所选文件后刷新真实素材列表", async () => {
  const load = vi.fn().mockResolvedValueOnce([]).mockResolvedValue([{asset_id: "one", name: "中文.mov", duration_ms: 22041, has_transcript: false, has_plan: false}]);
  const upload = vi.fn().mockResolvedValue({asset_id: "one"});
  render(<AssetLibrary projectId="demo" load={load} upload={upload} onOpen={vi.fn()} />);
  await screen.findByText("尚无素材");
  const file = new File(["media"], "中文.mov", {type: "video/quicktime"});
  await userEvent.upload(screen.getByLabelText("选择媒体文件"), file);
  await userEvent.click(screen.getByRole("button", {name: "导入素材"}));
  expect(await screen.findByRole("heading", {name: "中文.mov"})).toBeInTheDocument();
  expect(upload).toHaveBeenCalledWith("demo", file);
  expect(screen.getByText(/未转录/)).toBeInTheDocument();
});
it("上传失败保留文件供重试，不伪造素材", async () => {
  render(<AssetLibrary projectId="demo" load={vi.fn().mockResolvedValue([])} upload={vi.fn().mockRejectedValue(new Error("损坏媒体"))} onOpen={vi.fn()} />);
  await userEvent.upload(screen.getByLabelText("选择媒体文件"), new File(["bad"], "bad.mov", {type: "video/quicktime"}));
  await userEvent.click(screen.getByRole("button", {name: "导入素材"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("损坏媒体");
  expect(screen.getByRole("button", {name: "导入素材"})).toBeEnabled();
});
