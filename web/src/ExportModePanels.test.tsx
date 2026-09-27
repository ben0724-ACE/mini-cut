import {useState} from "react";
import {expect,it} from "vitest";
import {render,screen} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {ExportModePanels,type ExportMode} from "./ExportModePanels";

function Harness(){const [mode,setMode]=useState<ExportMode>("single");return <div className="tool-scroll"><ExportModePanels mode={mode} onChange={setMode} single={<label>单个封面草稿<input aria-label="单个封面草稿"/></label>} batch={<label>批量设置<input aria-label="批量设置"/></label>}/></div>;}

it("仅显示当前模式，切换保留两处草稿并回到顶部",async()=>{
  const user=userEvent.setup();const view=render(<Harness/>);
  expect(screen.getByRole("button",{name:"单个"})).toHaveAttribute("aria-pressed","true");
  expect(screen.getByLabelText("单个封面草稿")).toBeVisible();expect(screen.getByLabelText("批量设置")).not.toBeVisible();
  await user.type(screen.getByLabelText("单个封面草稿"),"待保存的封面");
  const scroll=view.container.querySelector(".tool-scroll")!;scroll.scrollTop=240;
  await user.click(screen.getByRole("button",{name:"批量"}));
  expect(scroll.scrollTop).toBe(0);expect(screen.getByRole("button",{name:"批量"})).toHaveAttribute("aria-pressed","true");
  expect(screen.getByLabelText("单个封面草稿")).not.toBeVisible();expect(screen.getByLabelText("批量设置")).toBeVisible();
  await user.type(screen.getByLabelText("批量设置"),"1080");
  await user.click(screen.getByRole("button",{name:"单个"}));
  expect(screen.getByLabelText("单个封面草稿")).toHaveValue("待保存的封面");
  await user.click(screen.getByRole("button",{name:"批量"}));expect(screen.getByLabelText("批量设置")).toHaveValue("1080");
});
