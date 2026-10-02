import {afterEach,expect,it,vi} from "vitest";
import {startOutputExportBatch} from "./api";
import {defaultExportOptions} from "./exportSettingsApi";
afterEach(()=>vi.unstubAllGlobals());
it("批量请求携带每条作品实际配置，几何覆盖保留各自字幕与音频参数",async()=>{
  const fetcher=vi.fn().mockResolvedValue({ok:true,json:async()=>[]});vi.stubGlobal("fetch",fetcher);
  await startOutputExportBatch("p","c",[{output_id:"a",revision:1},{output_id:"b",revision:2}],defaultExportOptions(),"batch",{b:{aspect_ratio:"4:5"}},{a:{...defaultExportOptions(),aspect_ratio:"9:16",subtitle_mode:"burned",audio_fade_ms:100},b:{...defaultExportOptions(),aspect_ratio:"1:1",crop_top:10}});
  const request=JSON.parse(fetcher.mock.calls[0][1].body);
  expect(request.outputs).toEqual([expect.objectContaining({collection_id:"c",output_id:"a",revision:1,aspect_ratio:"9:16",subtitle_mode:"burned",audio_fade_ms:100}),expect.objectContaining({collection_id:"c",output_id:"b",revision:2,aspect_ratio:"4:5",crop_top:10,subtitle_mode:"soft"})]);
});
