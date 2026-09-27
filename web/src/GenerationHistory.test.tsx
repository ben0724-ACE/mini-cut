import { expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GenerationHistory } from "./GenerationHistory";
import { getGenerationHistory, type GenerationHistoryEntry } from "./api";
vi.mock("./api",()=>({getGenerationHistory:vi.fn()}));
const old:GenerationHistoryEntry={history_id:"old",asset_id:"one",asset_name:"访谈.mov",created_at:null,status:"failed",error:"额度不足",collection_id:null,brief:{preset:"opinion_first",instructions:"原始要求"},missing_fields:["preset_prompt","hook_ms","body_mode"]};

it("历史显示原文、未知字段和失败原因，载入不触发生成",async()=>{
  vi.mocked(getGenerationHistory).mockResolvedValue([old]);
  const load=vi.fn();
  render(<GenerationHistory project="demo" asset="one" refreshKey="old:failed" disabled={false} onLoad={load} />);
  expect(getGenerationHistory).not.toHaveBeenCalled();
  await userEvent.click(screen.getByText("生成历史"));
  expect(await screen.findByLabelText("历史剪辑要求")).toHaveValue("原始要求");
  expect(screen.getByLabelText("历史预设提示词")).toHaveValue("未记录，无法确认当时使用的预设提示词");
  expect(screen.getByText("当次错误：额度不足")).toBeInTheDocument();
  expect(screen.getByRole("option",{name:/时间未记录/})).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"载入为草稿"}));
  expect(load).toHaveBeenCalledWith(old);
  await userEvent.selectOptions(screen.getByLabelText("历史范围"),"project");
  await waitFor(()=>expect(getGenerationHistory).toHaveBeenLastCalledWith("demo",undefined,expect.any(AbortSignal)));
});

it("生成状态变化后刷新历史，失败可重试而非展示旧范围记录",async()=>{
  vi.mocked(getGenerationHistory).mockResolvedValueOnce([old]).mockRejectedValueOnce(new Error("历史读取失败")).mockResolvedValueOnce([]);
  const view=render(<GenerationHistory project="demo" asset="one" refreshKey="old:failed" disabled onLoad={vi.fn()} />);
  await userEvent.click(screen.getByText("生成历史"));
  expect(await screen.findByRole("button",{name:"载入为草稿"})).toBeDisabled();
  view.rerender(<GenerationHistory project="demo" asset="one" refreshKey="new:pending" disabled onLoad={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("历史读取失败");
  expect(screen.queryByLabelText("历史剪辑要求")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"重试读取历史"}));
  expect(await screen.findByText("尚无生成历史")).toBeInTheDocument();
});
