import { it,expect,vi } from "vitest";
import { act,render,screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Workbench } from "./Workbench";
it("单播放器与标签面板，切换后保留草稿",async()=>{
  const view=render(<Workbench sidebar={<p>候选</p>} preview={<video aria-label="成片" />} generate={<input aria-label="草稿" />} edit={<p>编辑内容</p>} exportPanel={<p>导出内容</p>} />);
  expect(view.container.querySelectorAll("video")).toHaveLength(1);
  await userEvent.type(screen.getByLabelText("草稿"),"要求");
  await userEvent.click(screen.getByRole("tab",{name:"编辑"}));
  expect(screen.getByText("编辑内容")).toBeVisible();
  await userEvent.click(screen.getByRole("tab",{name:"生成"}));
  expect(screen.getByLabelText("草稿")).toHaveValue("要求");
});
it("键盘切换面板，收起再展开不丢草稿",async()=>{
  const user=userEvent.setup();
  render(<Workbench sidebar={null} preview={null} generate={<input aria-label="生成草稿" />} edit={<p>编辑</p>} exportPanel={<p>导出</p>} />);
  await user.type(screen.getByLabelText("生成草稿"),"保留");
  screen.getByRole("tab",{name:"生成"}).focus();
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab",{name:"编辑"})).toHaveFocus();
  expect(screen.getByRole("tab",{name:"编辑"})).toHaveAttribute("aria-selected","true");
  const collapse=screen.getByRole("button",{name:"收起右侧面板"});
  expect(collapse.closest(".workbench-tools")).not.toBeNull();
  expect(collapse).toHaveAttribute("aria-expanded","true");
  await user.click(collapse);
  expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  const expand=screen.getByRole("button",{name:"展开右侧面板"});
  expect(expand.closest(".workbench-preview")).not.toBeNull();
  expect(expand).toHaveAttribute("aria-expanded","false");
  expect(expand).toHaveFocus();
  expect(document.getElementById(expand.getAttribute("aria-controls")!)).not.toBeVisible();
  await user.keyboard("{Enter}");
  expect(screen.getByRole("button",{name:"收起右侧面板"})).toHaveFocus();
  await user.click(screen.getByRole("tab",{name:"生成"}));
  expect(screen.getByLabelText("生成草稿")).toHaveValue("保留");
});

it("窄屏使用工具面板文案，调整窗口后同步方向描述",async()=>{
  const media={matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()};
  vi.stubGlobal("matchMedia",vi.fn(()=>media));
  try{
    const view=render(<Workbench sidebar={null} preview={null} generate={null} edit={null} exportPanel={null}/>);
    await userEvent.click(screen.getByRole("button",{name:"收起工具面板"}));
    expect(screen.getByRole("button",{name:"展开工具面板"})).toBeVisible();
    const update=media.addEventListener.mock.calls[0][1] as ()=>void;
    act(()=>{media.matches=false;update();});
    await userEvent.click(screen.getByRole("button",{name:"展开右侧面板"}));
    expect(screen.getByRole("button",{name:"收起右侧面板"})).toBeVisible();
    view.unmount();
    expect(media.removeEventListener).toHaveBeenCalledWith("change",update);
  }finally{vi.unstubAllGlobals();}
});
