import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { ProjectHome } from "./ProjectHome";

describe("ProjectHome", () => {
  it("keeps keyboard focus inside the dialog and restores it on Escape", async () => {
    const user = userEvent.setup();
    render(<ProjectHome loadProjects={vi.fn().mockResolvedValue([])} createProject={vi.fn()} onSelect={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "新建项目" }));
    const input = screen.getByLabelText("项目名称");
    expect(input).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "取消" })).toHaveFocus();
    await user.tab();
    expect(input).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新建项目" })).toHaveFocus();
  });
  it("shows an empty list and creates without asking for IDs", async () => {
    const user = userEvent.setup();
    const create = vi.fn().mockResolvedValue({ project_id: "new-id", name: "播客", asset_count: 0, asset_ids: [] });
    const select = vi.fn();
    render(<ProjectHome loadProjects={vi.fn().mockResolvedValue([])} createProject={create} onSelect={select} />);
    expect(await screen.findByText("还没有项目")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "新建项目" }));
    await user.type(screen.getByLabelText("项目名称"), "播客");
    await user.click(screen.getByRole("button", { name: "创建并进入" }));
    expect(create).toHaveBeenCalledWith("播客");
    await waitFor(() => expect(select).toHaveBeenCalledWith("new-id"));
  });

  it("keeps the name and dialog after creation fails", async () => {
    const user = userEvent.setup();
    render(<ProjectHome loadProjects={vi.fn().mockResolvedValue([])} createProject={vi.fn().mockRejectedValue(new Error("磁盘不可写"))} onSelect={vi.fn()} />);
    await screen.findByText("还没有项目");
    await user.click(screen.getByRole("button", { name: "新建项目" }));
    await user.type(screen.getByLabelText("项目名称"), "保留输入");
    await user.click(screen.getByRole("button", { name: "创建并进入" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("磁盘不可写");
    expect(screen.getByLabelText("项目名称")).toHaveValue("保留输入");
  });

  it("selects an existing project and retries a failed list", async () => {
    const user = userEvent.setup();
    const load = vi.fn().mockRejectedValueOnce(new Error("离线")).mockResolvedValue([{ project_id: "one", name: "项目一", asset_count: 2 }]);
    const select = vi.fn();
    render(<ProjectHome loadProjects={load} createProject={vi.fn()} onSelect={select} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("离线");
    await user.click(screen.getByRole("button", { name: "重试" }));
    await user.click(await screen.findByRole("button", { name: "进入项目一" }));
    expect(select).toHaveBeenCalledWith("one");
  });
});

it("confirms deletion, preserves a failed project and removes it after success", async () => {
  const user = userEvent.setup();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({detail:"任务运行中"}), {status:409})).mockResolvedValueOnce(new Response(JSON.stringify({deleted:true})));
  render(<ProjectHome loadProjects={vi.fn().mockResolvedValue([{project_id:"one",name:"测试",asset_count:1}])} createProject={vi.fn()} onSelect={vi.fn()} />);
  await user.click(await screen.findByRole("button",{name:"删除测试"}));
  expect(fetcher).not.toHaveBeenCalled();
  confirm.mockReturnValue(true);
  await user.click(screen.getByRole("button",{name:"删除测试"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("任务运行中");
  expect(screen.getByRole("button",{name:"进入测试"})).toBeInTheDocument();
  await user.click(screen.getByRole("button",{name:"删除测试"}));
  expect(await screen.findByText("还没有项目")).toBeInTheDocument();
  confirm.mockRestore(); fetcher.mockRestore();
});
