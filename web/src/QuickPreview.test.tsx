import { fireEvent,render,screen } from "@testing-library/react";
import { expect,it,vi } from "vitest";
import { QuickPreview } from "./QuickPreview";
it("试听结尾只播放最后三秒并停止，播放全部保留顺序",()=>{
  vi.spyOn(HTMLMediaElement.prototype,"play").mockResolvedValue();
  const pause=vi.spyOn(HTMLMediaElement.prototype,"pause").mockImplementation(()=>{});
  const clips=[{instance_id:"a",segment_id:"a",role:"body" as const,text:"A",start_ms:10000,end_ms:18000},{instance_id:"b",segment_id:"b",role:"body" as const,text:"B",start_ms:30000,end_ms:35000}];
  render(<QuickPreview sourceUrl="/source" title="T" clips={clips} audition={{id:"a",part:"end",sequence:1}} onDuration={vi.fn()} />);
  const video=screen.getByLabelText("快速预览 · T") as HTMLVideoElement;
  expect(video.currentTime).toBe(15);
  video.currentTime=18.1;fireEvent.timeUpdate(video);expect(pause).toHaveBeenCalled();expect(video.currentTime).toBe(18);
  fireEvent.click(screen.getByText("播放全部片段"));expect(video.currentTime).toBe(10);
  video.currentTime=18;fireEvent.timeUpdate(video);expect(video.currentTime).toBe(30);
});
