import { expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { getGenerationDraft, saveGenerationDraft, type GenerationDraftResponse, type GenerationHistoryEntry } from "./api";
import { HighlightForm } from "./HighlightForm";
import { defaultGenerationDraft, type GenerationDraft } from "./generationDraft";
import { useGenerationDraft } from "./useGenerationDraft";
vi.mock("./api",()=>({getGenerationDraft:vi.fn(),saveGenerationDraft:vi.fn()}));
function Harness({project="demo",history}:{project?:string;history?:GenerationHistoryEntry}) {
  const state=useGenerationDraft(project,"one");
  return <><p>{state.notice}</p><p>{state.loaded?(state.saveError?"保存失败":state.saving?"保存中":"已保存"):"读取中"}</p><HighlightForm draft={state.draft} onChange={state.change} ready busy={!state.loaded} onSubmit={vi.fn()} /><button onClick={()=>void state.flush().catch(()=>{})}>重试保存</button>{history&&<button onClick={()=>state.loadHistory(history)}>载入历史</button>}</>;
}
function deferred<T>() {
  let resolve!:(value:T)=>void;
  const promise=new Promise<T>(done=>{resolve=done;});
  return {promise,resolve};
}

it("快速输入顺序保存最新值，旧响应不会覆盖草稿",async()=>{
  const draft=defaultGenerationDraft();
  vi.mocked(getGenerationDraft).mockResolvedValue({source:"asset",draft});
  const first=deferred<GenerationDraftResponse>();
  vi.mocked(saveGenerationDraft).mockReset().mockReturnValueOnce(first.promise).mockImplementation(async(_project,_asset,draft)=>({source:"asset",draft}));
  render(<Harness project="queue" />);
  await screen.findByText("已保存");
  fireEvent.change(screen.getByLabelText("剪辑要求"),{target:{value:"第一版"}});
  fireEvent.change(screen.getByLabelText("剪辑要求"),{target:{value:"第二版"}});
  fireEvent.change(screen.getByLabelText("剪辑要求"),{target:{value:"最终版"}});
  expect(saveGenerationDraft).toHaveBeenCalledTimes(1);
  first.resolve({source:"asset",draft});
  await screen.findByText("已保存");
  expect(saveGenerationDraft).toHaveBeenCalledTimes(2);
  expect(saveGenerationDraft).toHaveBeenLastCalledWith("queue","one",expect.objectContaining({instructions:"最终版"}));
  expect(screen.getByLabelText("剪辑要求")).toHaveValue("最终版");
});

it("保存失败后的页面重开恢复本机未同步文本，重试保存到项目",async()=>{
  const initial=defaultGenerationDraft();
  vi.mocked(getGenerationDraft).mockResolvedValue({source:"asset",draft:initial});
  vi.mocked(saveGenerationDraft).mockReset().mockRejectedValue(new Error("磁盘暂不可写"));
  const first=render(<Harness project="retry" />);
  await screen.findByText("已保存");
  fireEvent.change(screen.getByLabelText("预设提示词"),{target:{value:"新提示词"}});
  fireEvent.change(screen.getByLabelText("剪辑要求"),{target:{value:"不能丢的要求"}});
  await screen.findByText("保存失败");
  first.unmount();
  vi.mocked(saveGenerationDraft).mockImplementation(async(_project,_asset,draft)=>({source:"asset",draft}));
  const reopened=render(<Harness project="retry" />);
  await screen.findByText("已保存");
  expect(screen.getByLabelText("预设提示词")).toHaveValue("新提示词");
  expect(screen.getByLabelText("剪辑要求")).toHaveValue("不能丢的要求");
  expect(saveGenerationDraft).toHaveBeenLastCalledWith("retry","one",expect.objectContaining({instructions:"不能丢的要求"}));
  reopened.unmount();
  localStorage.setItem("minicut:generation-draft:reload:one",JSON.stringify({...initial,instructions:"刷新前未同步"}));
  render(<Harness project="reload" />);
  await screen.findByText("已保存");
  expect(screen.getByLabelText("剪辑要求")).toHaveValue("刷新前未同步");
  expect(localStorage.getItem("minicut:generation-draft:reload:one")).toBeNull();
});

it("读取前等待上一面板的保存，防止返回旧草稿",async()=>{
  const initial=defaultGenerationDraft();
  let persisted:GenerationDraft=initial;
  vi.mocked(getGenerationDraft).mockImplementation(async()=>({source:"asset",draft:persisted}));
  const saving=deferred<GenerationDraftResponse>();
  vi.mocked(saveGenerationDraft).mockReset().mockReturnValueOnce(saving.promise).mockImplementation(async(_project,_asset,draft)=>({source:"asset",draft}));
  const view=render(<Harness project="navigation" />);
  await screen.findByText("已保存");
  fireEvent.change(screen.getByLabelText("剪辑要求"),{target:{value:"切换前最新文本"}});
  view.unmount();
  render(<Harness project="navigation" />);
  expect(screen.getByText("读取中")).toBeInTheDocument();
  persisted={...initial,instructions:"切换前最新文本"};
  saving.resolve({source:"asset",draft:persisted});
  await screen.findByText("已保存");
  expect(screen.getByLabelText("剪辑要求")).toHaveValue("切换前最新文本");
});

it("载入旧历史只修改草稿，原始记录保持不变并提示默认补齐",async()=>{
  vi.mocked(getGenerationDraft).mockResolvedValue({source:"asset",draft:defaultGenerationDraft()});
  vi.mocked(saveGenerationDraft).mockReset().mockImplementation(async(_project,_asset,draft)=>({source:"asset",draft}));
  const history:GenerationHistoryEntry={history_id:"old",asset_id:"one",asset_name:"素材",created_at:null,status:"succeeded",error:null,collection_id:"old",brief:{preset:"opinion_first",preset_prompt:"旧自定义提示词",instructions:"旧要求",hook_ms:12500,translation_language:"en"},missing_fields:["body_mode"]};
  const original=JSON.stringify(history);
  render(<Harness project="history" history={history} />);
  await screen.findByText("已保存");
  await userEvent.click(screen.getByRole("button",{name:"载入历史"}));
  await waitFor(()=>expect(saveGenerationDraft).toHaveBeenCalled());
  expect(screen.getByLabelText("预设提示词")).toHaveValue("旧自定义提示词");
  expect(screen.getByLabelText("剪辑要求")).toHaveValue("旧要求");
  expect(screen.getByLabelText("开场预告目标秒数")).toHaveValue(12.5);
  expect(screen.getByLabelText("翻译为")).toHaveValue("en");
  expect(screen.getByText(/默认值不代表当时的配置/)).toBeInTheDocument();
  expect(JSON.stringify(history)).toBe(original);
});

it("旧格式草稿和带自定义预设的未同步草稿都能恢复",async()=>{
  const initial=defaultGenerationDraft();
  const {custom_preset_id:_id,custom_preset_name:_name,custom_prompt:_prompt,...legacy}=initial;
  vi.mocked(getGenerationDraft).mockResolvedValue({source:"asset",draft:legacy});
  vi.mocked(saveGenerationDraft).mockReset().mockImplementation(async(_project,_asset,draft)=>({source:"asset",draft}));
  const old=render(<Harness project="legacy-compatible" />);
  await screen.findByText("已保存");
  expect(screen.getByLabelText("预设提示词")).toHaveValue(initial.prompts[initial.preset]);
  old.unmount();
  const custom={...initial,custom_preset_id:"deleted",custom_preset_name:"已删除的模板",custom_prompt:"未同步的自定义文字"};
  localStorage.setItem("minicut:generation-draft:custom-reload:one",JSON.stringify(custom));
  render(<Harness project="custom-reload" />);
  await screen.findByText("已保存");
  expect(screen.getByLabelText("预设提示词")).toHaveValue("未同步的自定义文字");
  expect(saveGenerationDraft).toHaveBeenLastCalledWith("custom-reload","one",expect.objectContaining({custom_preset_id:"deleted",custom_preset_name:"已删除的模板",custom_prompt:"未同步的自定义文字"}));
});
