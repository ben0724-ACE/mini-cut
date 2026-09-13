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
