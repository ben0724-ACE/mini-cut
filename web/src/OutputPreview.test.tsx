import { expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { OutputPreview } from "./OutputPreview";

it("加载后直接定位首段，原生播放按钮也按计划播放",()=>{
  vi.spyOn(HTMLMediaElement.prototype,"pause").mockImplementation(()=>{});
  render(<OutputPreview title="起点" mediaUrl="/source" clips={[{instance_id:"a",segment_id:"s",role:"body",text:"首段",start_ms:10000,end_ms:12000}]} />);
  const video=screen.getByLabelText("播放器 · 起点") as HTMLVideoElement;
  fireEvent.loadedMetadata(video);
  expect(video.currentTime).toBe(10);
  fireEvent.play(video);video.currentTime=12;fireEvent.timeUpdate(video);
  expect(video.pause).toHaveBeenCalled();
});

it("按实例顺序播放，支持原话钩子后向前跳转正文", () => {
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  render(<OutputPreview title="作品A" mediaUrl="/source" clips={[{instance_id:"hook",segment_id:"s2",role:"hook",text:"结论",start_ms:10000,end_ms:12000},{instance_id:"body",segment_id:"s1",role:"body",text:"背景",start_ms:1000,end_ms:3000}]} />);
  fireEvent.click(screen.getByRole("button", {name:"预览作品A"}));
  const video = screen.getByLabelText("播放器 · 作品A") as HTMLVideoElement;
  expect(video.currentTime).toBe(10);
  video.currentTime = 12; fireEvent.timeUpdate(video);
  expect(video.currentTime).toBe(1);
  video.currentTime = 3; fireEvent.timeUpdate(video);
  expect(video.pause).toHaveBeenCalled();
});
