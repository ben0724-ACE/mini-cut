import { it,expect } from "vitest";
import { render,screen } from "@testing-library/react";
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
