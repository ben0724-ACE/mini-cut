import { expect, it, vi } from "vitest";
import { navigateToExportResults } from "./exportNavigation";

it("进入结果页前把当前历史记录保存为导出面板",()=>{
  window.history.replaceState({},"","/?project=p");
  const replace=vi.spyOn(window.history,"replaceState");
  const push=vi.spyOn(window.history,"pushState");
  navigateToExportResults("p","c",[{outputId:"o",taskId:"t"}]);
  expect(replace).toHaveBeenCalledWith({},"","/?project=p&panel=export");
  expect(push).toHaveBeenCalledWith({},"","/?project=p&view=exports&collection=c&output=o&task=t");
  replace.mockRestore();
  push.mockRestore();
  window.history.replaceState({},"","/");
});
