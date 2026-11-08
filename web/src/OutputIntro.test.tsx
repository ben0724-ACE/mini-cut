import {fireEvent,render,screen,waitFor} from "@testing-library/react";
import {expect,it,vi} from "vitest";
import {OutputIntro} from "./OutputIntro";
import * as introApi from "./introApi";
import type {HighlightOutput} from "./api";

vi.mock("./api",async original=>({...await original<typeof import("./api")>(),listSubtitleFonts:vi.fn().mockResolvedValue([{id:"configured",name:"Arial Unicode MS"},{id:"heiti",name:"黑体（中文）"},{id:"hiragino",name:"冬青黑体（中文）"}])}));

vi.mock("./introApi",async original=>({...await original<typeof import("./introApi")>(),uploadIntroAudio:vi.fn(),getIntroAudio:vi.fn()}));

const plan:HighlightOutput={output_id:"o",title:"讨论 AI 安全",social_copy:"先理解能力与控制的关系。然后再讨论应对方法。",reason:"",revision:1,duration_ms:5000,clips:[{instance_id:"i",segment_id:"s",role:"body",text:"原话",start_ms:1000,end_ms:6000}]};

it("旧作品默认关闭，启用后可复用标题和完整作品简介再保存",async()=>{
  const dirty=vi.fn(),save=vi.fn().mockResolvedValue(undefined);
  render(<OutputIntro plan={plan} sourceUrl="/source.mp4" disabled={false} onDirty={dirty} onSave={save}/>);
  expect(screen.getByLabelText("启用开场导读")).not.toBeChecked();
  expect(screen.getByRole("button",{name:"保存导读"})).toBeDisabled();
  fireEvent.click(screen.getByLabelText("启用开场导读"));
  expect(screen.getByLabelText("导读标题")).toHaveValue(plan.title);
  fireEvent.click(screen.getByRole("button",{name:"使用作品简介"}));
  expect(screen.getByLabelText("导读介绍")).toHaveValue(plan.social_copy);
  expect(dirty).toHaveBeenLastCalledWith(true);
  fireEvent.click(screen.getByRole("button",{name:"保存导读"}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith({title:plan.title,text:plan.social_copy,duration_ms:5000,frame_ms:null,music:true,motion:true,font_id:null,motion_style:"rise",music_version:2,motion_strength:1,transition_ms:600,audio_id:null}));
});

it("超长简介保留原文并提示精简，不静默截断",()=>{
  render(<OutputIntro plan={{...plan,social_copy:"字".repeat(181)}} sourceUrl="/s" disabled={false} onDirty={vi.fn()} onSave={vi.fn()}/>);
  fireEvent.click(screen.getByLabelText("启用开场导读"));
  fireEvent.click(screen.getByRole("button",{name:"使用作品简介"}));
  expect(screen.getByLabelText("导读介绍")).toHaveValue("字".repeat(181));
  expect(screen.getByRole("button",{name:"保存导读"})).toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent("180 字以内");
});

it("导读可独立选字体、轻盈动效与配乐方案",async()=>{
  const save=vi.fn().mockResolvedValue(undefined);
  const view=render(<OutputIntro plan={plan} sourceUrl="/s" disabled={false} onDirty={vi.fn()} onSave={save}/>);
  fireEvent.click(screen.getByLabelText("启用开场导读"));
  await screen.findByRole("option",{name:"冬青黑体（中文）"});
  fireEvent.change(screen.getByLabelText("导读字体"),{target:{value:"hiragino"}});
  expect(screen.getByLabelText("动效样式")).toHaveValue("rise");
  expect(screen.getByLabelText("配乐来源")).toHaveValue("builtin");
  fireEvent.click(screen.getByRole("button",{name:"播放动效示意"}));
  expect(view.container.querySelector(".intro-layout--rise")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"保存导读"}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith(expect.objectContaining({font_id:"hiragino",motion_style:"rise",music_version:2})));
});

it("新导读默认启用柔和动效，旧导读保留静态设置，开关可保存",async()=>{
  const save=vi.fn().mockResolvedValue(undefined);
  const view=render(<OutputIntro plan={plan} sourceUrl="/s" disabled={false} onDirty={vi.fn()} onSave={save}/>);
  fireEvent.click(screen.getByLabelText("启用开场导读"));
  expect(screen.getByLabelText("柔和文字动效")).toBeChecked();
  fireEvent.click(screen.getByRole("button",{name:"播放动效示意"}));
  expect(view.container.querySelector(".intro-layout--motion")).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("柔和文字动效"));
  fireEvent.click(screen.getByRole("button",{name:"保存导读"}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith(expect.objectContaining({motion:false})));
  const old={...plan,intro:{title:"原导读",text:"原介绍",duration_ms:5000,frame_ms:null,music:true}};
  view.rerender(<OutputIntro key="old" plan={old} sourceUrl="/s" disabled={false} onDirty={vi.fn()} onSave={save}/>);
  expect(screen.getByLabelText("柔和文字动效")).not.toBeChecked();
  expect(screen.getByRole("button",{name:"保存导读"})).toBeDisabled();
  fireEvent.click(screen.getByLabelText("柔和文字动效"));
  fireEvent.click(screen.getByRole("button",{name:"保存导读"}));
  await waitFor(()=>expect(save).toHaveBeenLastCalledWith(expect.objectContaining({motion:true})));
});

it("只允许保留片段中的背景帧，并允许关闭音乐",async()=>{
  const save=vi.fn().mockResolvedValue(undefined);
  render(<OutputIntro plan={plan} sourceUrl="/s" disabled={false} onDirty={vi.fn()} onSave={save}/>);
  fireEvent.click(screen.getByLabelText("启用开场导读"));
  fireEvent.click(screen.getByText(/选择背景帧/));
  const video=screen.getByLabelText("选择导读背景帧") as HTMLVideoElement;
  video.currentTime=0;
  fireEvent.click(screen.getByRole("button",{name:"使用当前画面"}));
  expect(screen.getByRole("alert")).toHaveTextContent("保留片段");
  video.currentTime=2.5;
  fireEvent.click(screen.getByRole("button",{name:"使用当前画面"}));
  fireEvent.click(screen.getByLabelText("播放导读配乐"));
  fireEvent.click(screen.getByRole("button",{name:"保存导读"}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith(expect.objectContaining({frame_ms:2500,music:false})));
});

it("保存失败保留草稿，放弃恢复保存值；可显式关闭已保存的导读",async()=>{
  const saved={...plan,intro:{title:"原导读",text:"原介绍",duration_ms:4000,frame_ms:2000,music:true}};
  const save=vi.fn().mockRejectedValueOnce(new Error("暂时无法保存"));
  const dirty=vi.fn();
  render(<OutputIntro plan={saved} sourceUrl="/s" disabled={false} onDirty={dirty} onSave={save}/>);
  fireEvent.change(screen.getByLabelText("导读标题"),{target:{value:"修改后的标题"}});
  fireEvent.click(screen.getByRole("button",{name:"保存导读"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法保存");
  expect(screen.getByLabelText("导读标题")).toHaveValue("修改后的标题");
  fireEvent.click(screen.getByRole("button",{name:"放弃导读修改"}));
  expect(screen.getByLabelText("导读标题")).toHaveValue("原导读");
  expect(dirty).toHaveBeenLastCalledWith(false);
  save.mockResolvedValueOnce(undefined);
  fireEvent.click(screen.getByLabelText("启用开场导读"));
  fireEvent.click(screen.getByRole("button",{name:"保存导读"}));
  await waitFor(()=>expect(save).toHaveBeenLastCalledWith(null));
});

it("导读样式直接编辑，自定义音乐与动效强度进入保存草稿",async()=>{
  const style={duration_ms:8000,font_id:"heiti",music:true,motion:true,motion_style:"rise" as const,motion_strength:1.8,transition_ms:1000,audio_id:null};
  vi.mocked(introApi.uploadIntroAudio).mockResolvedValueOnce({audio_id:"a".repeat(32),name:"我的音乐.wav",duration_ms:4000});
  vi.mocked(introApi.getIntroAudio).mockResolvedValue({audio_id:"a".repeat(32),name:"我的音乐.wav",duration_ms:4000});
  const save=vi.fn().mockResolvedValue(undefined);
  render(<OutputIntro plan={{...plan,intro:{title:"自己的标题",text:"自己的导读",frame_ms:2500,duration_ms:5000,music:true}}} sourceUrl="/s" disabled={false} onDirty={vi.fn()} onSave={save}/>);
  await screen.findByRole("option",{name:"黑体（中文）"});
  fireEvent.change(screen.getByLabelText("导读字体"),{target:{value:"heiti"}});
  fireEvent.change(screen.getByLabelText("导读时长（秒）"),{target:{value:"8"}});
  fireEvent.change(screen.getByLabelText("转黑过渡（秒）"),{target:{value:"1"}});
  fireEvent.click(screen.getByLabelText("柔和文字动效"));
  fireEvent.change(screen.getByLabelText("动效样式"),{target:{value:"rise"}});
  fireEvent.change(screen.getByLabelText("动效强度"),{target:{value:"1.8"}});
  expect(screen.queryByLabelText("导读预设")).not.toBeInTheDocument();
  expect(screen.getByLabelText("导读标题")).toHaveValue("自己的标题");
  expect(screen.getByLabelText("导读介绍")).toHaveValue("自己的导读");
  expect(screen.getByLabelText("动效强度")).toHaveValue("1.8");
  expect(screen.queryByText(/旧版/)).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("上传自己的 BGM"),{target:{files:[new File(["audio"],"我的音乐.wav",{type:"audio/wav"})]}});
  expect(screen.getByRole("button",{name:"保存导读"})).toBeDisabled();
  await waitFor(()=>expect(screen.getByRole("button",{name:"保存导读"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"保存导读"}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith(expect.objectContaining({...style,title:"自己的标题",text:"自己的导读",frame_ms:2500,audio_id:"a".repeat(32)})));
});
