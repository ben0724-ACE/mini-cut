import {beforeEach,expect,it,vi} from "vitest";
import {fireEvent,render,screen,waitFor} from "@testing-library/react";
import {BatchCoverTemplates} from "./BatchCoverTemplates";
import * as api from "./coverApi";
vi.mock("./coverApi",async original=>({...await original<typeof import("./coverApi")>(),listCoverTemplates:vi.fn(),applyBatchCoverTemplate:vi.fn()}));
const props={project:"p",collection:"c",outputs:[{output_id:"a",title:"作品A",revision:1},{output_id:"b",title:"作品B",revision:2},{output_id:"unselected",title:"未选择",revision:3}],selected:["a","b"],disabled:false,onBusy:vi.fn()};
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api.listCoverTemplates).mockResolvedValue([{template_id:"template",name:"共享模板",style:{} as api.CoverStyle,created_at:"now",updated_at:"now"}]);vi.mocked(api.applyBatchCoverTemplate).mockResolvedValue([{output_id:"a",version:2,error:null},{output_id:"b",version:null,error:"作品版本已变更"}]);});
it("只对选中的作品显式应用，逐条显示部分成功并通知当前封面刷新",async()=>{
  const listener=vi.fn();window.addEventListener(api.coversSaved,listener);
  render(<BatchCoverTemplates {...props}/>);fireEvent.click(screen.getByText("批量应用封面模板"));await screen.findByRole("option",{name:"共享模板"});
  fireEvent.change(screen.getByLabelText("批量封面模板"),{target:{value:"template"}});expect(api.applyBatchCoverTemplate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("全部设计 · 保存到已选作品"));
  await screen.findByText("已保存 1 条；失败 1 条。");
  expect(api.applyBatchCoverTemplate).toHaveBeenCalledWith("p","c",[{output_id:"a",revision:1},{output_id:"b",revision:2}],"template","all");
  expect(screen.getByRole("alert")).toHaveTextContent("作品版本已变更");
  expect(listener).toHaveBeenCalledOnce();const event=listener.mock.calls[0][0] as CustomEvent;
  expect(event.detail).toEqual({project:"p",collection:"c",outputs:["a"]});
  expect(props.onBusy).toHaveBeenLastCalledWith(false);window.removeEventListener(api.coversSaved,listener);
});
it("当前封面有未保存修改时不能批量应用",async()=>{
  render(<BatchCoverTemplates {...props} disabled/>);fireEvent.click(screen.getByText("批量应用封面模板"));await screen.findByRole("option",{name:"共享模板"});
  expect(screen.getByLabelText("批量封面模板")).toBeDisabled();expect(screen.getByText("仅标题样式 · 保存到已选作品")).toBeDisabled();
  expect(api.applyBatchCoverTemplate).not.toHaveBeenCalled();
});
it("操作进行中阻止重复请求",async()=>{
  let finish:((rows:api.BatchCoverResult[])=>void)|undefined;
  vi.mocked(api.applyBatchCoverTemplate).mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
  render(<BatchCoverTemplates {...props}/>);fireEvent.click(screen.getByText("批量应用封面模板"));await screen.findByRole("option",{name:"共享模板"});
  fireEvent.change(screen.getByLabelText("批量封面模板"),{target:{value:"template"}});const button=screen.getByText("全部设计 · 保存到已选作品");fireEvent.click(button);fireEvent.click(button);
  expect(api.applyBatchCoverTemplate).toHaveBeenCalledOnce();expect(button).toBeDisabled();
  finish?.([{output_id:"a",version:2,error:null}]);await waitFor(()=>expect(button).toBeEnabled());
});
