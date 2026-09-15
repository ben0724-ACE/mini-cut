import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TranscriptionControls } from "./TranscriptionControls";

it("转录辅助文案简短，详细说明默认折叠", () => {
  render(<TranscriptionControls project="demo" asset="asset" recover={vi.fn().mockResolvedValue(null)} />);
  expect(screen.getByText("本机转录 · 未缓存模型需联网下载")).toHaveClass("helper-text");
  expect(screen.getByText("转录说明").closest("details")).not.toHaveAttribute("open");
});

it("选择模型语言并提交注册素材，不发送路径", async () => {
  const start = vi.fn().mockResolvedValue({task_id: "job", status: "succeeded", result: {word_count: 47}, error: null});
  render(<TranscriptionControls project="demo" asset="asset" recover={vi.fn().mockResolvedValue(null)} start={start} />);
  const button = await screen.findByRole("button", {name: "开始转录"});
  await userEvent.selectOptions(screen.getByLabelText("语言"), "en");
  await userEvent.click(button);
  expect(await screen.findByText(/47 个词/)).toBeInTheDocument();
  expect(start).toHaveBeenCalledWith("demo", "asset", {provider: "mlx", model: "large-v3-turbo", language: "en"});
});
it("刷新恢复真实失败任务并显示错误", async () => {
  render(<TranscriptionControls project="demo" asset="asset" recover={vi.fn().mockResolvedValue({task_id: "old", status: "failed", result: null, error: "模型不可用"})} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("模型不可用");
  expect(screen.getByRole("button", {name: "开始转录"})).toBeEnabled();
});
it("恢复运行任务显示进度并自动读取完成结果", async () => {
  const read = vi.fn().mockResolvedValue({task_id: "old", status: "succeeded", result: {word_count: 47}, error: null});
  const complete = vi.fn();
  render(<TranscriptionControls project="demo" asset="asset" recover={vi.fn().mockResolvedValue({task_id: "old", status: "running", progress:{completed:2,total:8}, result: null, error: null})} read={read} onComplete={complete} />);
  expect(await screen.findByRole("progressbar", {name:"转录进度"})).toHaveAttribute("value","2");
  expect(screen.queryByRole("button",{name:"停止查询"})).not.toBeInTheDocument();
  expect(await screen.findByText(/47 个词/, {}, {timeout: 2500})).toBeInTheDocument();
  expect(complete).toHaveBeenCalledOnce();
});
