import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TranscriptionControls } from "./TranscriptionControls";

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
it("恢复运行任务，可暂停查询再恢复并读取完成结果", async () => {
  const read = vi.fn().mockResolvedValue({task_id: "old", status: "succeeded", result: {word_count: 47}, error: null});
  const complete = vi.fn();
  render(<TranscriptionControls project="demo" asset="asset" recover={vi.fn().mockResolvedValue({task_id: "old", status: "running", result: null, error: null})} read={read} onComplete={complete} />);
  await userEvent.click(await screen.findByRole("button", {name: "停止查询"}));
  expect(screen.getByRole("status")).toHaveTextContent("已停止查询");
  expect(read).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", {name: "恢复查询"}));
  expect(await screen.findByText(/47 个词/, {}, {timeout: 2500})).toBeInTheDocument();
  expect(complete).toHaveBeenCalledOnce();
});
