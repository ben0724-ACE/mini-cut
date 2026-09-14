# MiniCut

## 当前能力与完整操作说明（中文）

MiniCut 是本地优先的口播视频粗剪与精选工作台。适合讲座、教程、访谈、播客和单人口播：导入视频 → 逐词转录 → AI 选材 → 预览和编辑 → 导出 MP4/SRT。

### 已实现的功能

| 功能 | 可以做什么 |
| --- | --- |
| 项目和素材 | 创建命名项目、切换项目、浏览器上传、素材列表、原视频预览；原媒体保留 |
| 转录 | MLX（Apple Silicon）或 PyTorch Whisper；Web 支持中文/英文选择、词级时间戳；复用共享模型和转录缓存 |
| 长视频 | 超过十分钟采用五分钟音频块及重叠时间映射，失败恢复已保存块；真实 64m47s 素材已跑通 |
| AI 精选 | 播客精选、知识精华、观点先行、口播清理；自定义要求、数量、时长、源内容重复上限；长文本分章分析并回到原文精修 |
| 开场钩子 | 复制一段吸引注意的原话到最前面，再播放完整的所选正片；正片保留原句。可由 AI 选择，也可手动添加/取消 |
| 钩子转场 | 预告末尾渐隐到黑/静音，正片开头渐入画面/声音，通常各 300ms；自动应用于有钩子的预览和导出，无钩子不添加 |
| 精修 | 字幕显示文字修改、原视频时间跳转、按片段删除/恢复、重排、版本记录；原词 ID 与源时间仍可追溯 |
| 导出 | 单条/批量 MP4、独立 SRT、可关闭的软字幕或烧录字幕、720/1080 档；原比例、16:9、9:16、1:1、4:5；整帧加边框或居中裁切；可单条覆盖批量画幅 |
| 任务和成本 | 后台状态、合作式取消、显式恢复、逐条导出重试；本地已完成模型结果复用、DeepSeek Token/缓存指标及可配置费用估算 |
| CLI/API | 命令行转录、规划、渲染、审阅；本地 HTTP API 和交互文档；下方英文部分列出 CLI 示例 |

“完整正片”指当前作品选出的完整论述，不是把整段一小时原文件附在钩子后。手动删除/重排仍然会改变正片。钩子约五秒，以完整原话和必要限定为先；无法找到合适原话时会说明不足，不承诺每次都生成优秀钩子。转场不交叠两段讲话、不另插空白时长，因此总时长为钩子加正片，字幕时间不移动。极短片段的转场会缩短。

当前不具备自动人物跟踪、智能构图、B-roll、配乐生成、旁白生成或复杂特效。裁切只是居中裁切。超出章节预算的不可分超长单段仍需另行处理；任意长度口播的完整清理不等同于精选模式。语音识别尤其是否定词、专有名词，仍需人工听核。长视频实测在 Apple M5/MLX 上完成，不能代表 Windows/Linux/PyTorch 都已实测。

### 1. 启动（当前电脑）

已有服务运行时直接打开 `http://127.0.0.1:5173`，不要重复启动。当前验收项目根目录为 `manual-test/web-projects`，后端使用 8001；以下两个终端要保持运行。

终端一：

```bash
cd /Users/ben/study/projects/mini-cut
MINICUT_PROJECTS_ROOT="$PWD/manual-test/web-projects" \
MINICUT_API_PORT=8001 HF_HUB_OFFLINE=1 \
uv run --no-sync --env-file .env minicut-api
```

终端二：

```bash
cd /Users/ben/study/projects/mini-cut/web
MINICUT_API_URL=http://127.0.0.1:8001 npm run dev -- --host 127.0.0.1
```

打开 `http://127.0.0.1:5173`。API 文档为 `http://127.0.0.1:8001/docs`。若端口被占用，使用已有服务，或一起修改后端端口和前端 `MINICUT_API_URL`。更换项目根目录会显示另一组项目；需要保留当前项目就保持以上目录。

仅新电脑首次安装时：准备 Python 3.11+、uv、Node/npm、FFmpeg/ffprobe；在仓库根目录运行 `uv sync --inexact`，Apple Silicon 使用 `uv pip install mlx-whisper`；在 `web` 运行 `npm ci`。其他平台使用已支持的 PyTorch Whisper 后端需另装 `openai-whisper`。首次没有模型缓存时不要设 `HF_HUB_OFFLINE=1`，允许转录后端下载所选模型，之后再离线启动。当前电脑已有 AutoCut 下载的共享 MLX 模型，无需重复下载。

`.env` 需要已有的 `DEEPSEEK_API_KEY`，可选 `DEEPSEEK_MODEL` 和 `DEEPSEEK_BASE_URL`；新环境参照 `.env.example` 手动创建，切勿覆盖现有密钥。`--no-sync` 适用于已经装好的当前环境，可避免启动时改动依赖。

### 2. 创建项目与导入

1. 点击「我的项目」，创建项目并填写名称；或打开已有项目。
2. 展开「导入素材」，选择本地视频，等待导入完成。
3. 在「当前素材」切换需要处理的视频。浏览器上传会在项目目录保存一份副本，需要相应磁盘空间。

### 3. 转录

1. 展开「转录设置」。当前 Mac 选择 MLX、`large-v3-turbo`，再选择视频实际语言。
2. 开始转录；长素材逐块保存进度。
3. 显示完成后进入生成。切换页面/刷新不会删除已保存结果。
4. 失败时先查看原因并修复，再点恢复；已完成块会复用。改模型/语言需要相应重新计算。

### 4. 生成精选和开场预告

1. 进入「生成」，选择预设。观点先行也需要明确勾选「约五秒原话钩子」。切换预设不会自动覆盖已有文字/参数。
2. 写明目标主题、受众、应保留的背景。例：

   > 选出两个不同主题，每条60至120秒。先放约五秒、能吸引注意的完整原话预告，再接完整论述。保留否定、限定和必要背景，不生成旁白。

3. 展开高级参数，设置数量、最短/最长秒数、源内容重复上限，并勾选钩子。时长上限包含钩子。
4. 点击「生成候选」。此步发送转录文本给 DeepSeek，可能付费；视频不发送给 DeepSeek。
5. 查看候选标题、理由、时长与不足说明；内容不足会少返回或没有候选。查看生成详情与 AI 用量可了解复用、实际 Token 和估算费用。

### 5. 预览和编辑

1. 点击候选自动生成低分辨率成片预览；预览播放的是剪后的作品。
2. 在「编辑」修正显示字幕，逐条点击「保存字幕」。字幕修改不会修改原声音。
3. 删除不需要的片段，误删可恢复；字幕草稿与删除操作分别保存。
4. 展开「片段顺序与开场原话」，对合适的正文片段点击「添加为开场预告」。系统复制开场实例，正文保持完整及原顺序；「取消开场预告」去掉开场副本，保留正文中的原片段。
5. 有钩子时自动加入预告→正片的声画渐隐渐入，无需打开普通切点淡入淡出参数。预览和最终导出使用同一规则。
6. 用上移/下移调整允许的片段顺序。钩子只能在正文之前；至少保留一段正文。修改会生成新版本。
7. 点击原时间按钮检查源视频，随后返回成片预览；展开版本记录可查看旧版本，历史只读。

### 6. 导出与下载

1. 单条：在「导出」设置画幅、分辨率、适配方式、字幕类型，再点「导出当前作品」。
2. 多条：在左侧勾选「加入批量」，配置「批量导出设置」；在「批量画幅与单条覆盖」指定统一画幅或逐条覆盖，点击「导出已选作品」。
3. 默认完整加边框，不拉伸画面；居中裁切会去掉边缘内容。横版幻灯片改成竖屏并保留全部画面时会有明显黑边。
4. 软字幕可由播放器开关；烧录字幕永久进入画面。中文烧录需要可读的中文字体；macOS 自动查找系统字体，找不到时按错误提示设置字体路径与字体名称。
5. 普通切点淡入淡出和降噪默认关闭，与自动钩子转场是两项不同功能。
6. 等每条任务成功后点击视频/字幕下载。失败仅重试该条；每次导出独立保存，不覆盖其他导出或原文件。

### 7. 恢复、退出与文件位置

- 「停止查询」只是停止界面轮询；真正停止计算要用取消。MLX/模型请求可能要等当前块或请求结束才确认取消。
- 后端重启后不自动续跑；使用恢复入口。已保存成功块/模型响应会复用，响应尚未保存的付费请求可能再次调用。
- 每个 API 进程最多执行一个重任务；不要对同一个项目根目录启动多个 API 来绕过限制。
- 原素材副本、转录和任务保存在项目目录；输出在该项目的 `exports/` 下。退出前等待保存，服务终端用 Ctrl+C 结束；之后用相同目录启动即可继续。
- 发布前听核字幕与原话、确认背景完整。程序检查源引用和时间约束，不能替代对“是否吸引人、是否断章取义”的人工判断。

2026-09-14 钩子复验：真实素材添加 5.00s 预告，正文仍为原来的 82.94s，导出总长 87.94s；边界画面由亮变黑再恢复，自动声画渐变经真实 FFmpeg 回归测量。此前的全部长视频、恢复、界面和费用实测见下方英文记录。


MiniCut is a local-first, AI-assisted rough-cutting tool for spoken videos. It turns a source video into a reviewable edit plan, then renders the approved timeline with deterministic media tooling.

## Product direction

The first supported workflow targets Chinese single-speaker videos such as tutorials, talking-head recordings, lectures, and podcasts. The initial product will focus on:

- word-timestamped transcription;
- removal of silence, filler, repetition, and false starts;
- duration- and style-aware edit planning;
- validated, reversible edit plans;
- subtitle and video export;
- human review before final delivery.

## Architecture

```text
Media input
    -> transcription
    -> transcript normalization
    -> semantic segmentation
    -> edit planning
    -> timeline validation
    -> FFmpeg rendering
    -> review and export
```

The model never invents media timestamps. It selects stable transcript segment identifiers; MiniCut resolves those identifiers to timestamps, validates the resulting timeline, and performs the actual cut.

Explicit output collections are also available through the Python application
services: each video has its own ordered source references and revision. A
source quote can appear as an opening hook and again in the complete excerpt,
with independently timed subtitle occurrences. Rendering these plans does not
call a language model. The Web workspace supports explicit ordered outputs,
opening quotes, read-only version history, individual and batch export. The
legacy CLI review remains source-ordered.

Python highlight planning supports speech cleanup, podcast highlights,
opinion-first excerpts and knowledge digests, with explicit count, duration,
hook and natural-language requirements. A measured selection pass preserves
context and limits source overlap. At most one semantic revision can respond
to measured failures or explicit reviewer feedback; insufficient material is
reported rather than padded. Excerpts still need human review for meaning,
titles and transcription accuracy.

## Current status

The media-ingestion and local-project foundation is complete. MLX Whisper and open-source Whisper share the same validated Transcript v1 output contract, including word timestamps and absolute time across VAD chunks. Deterministic semantic segmentation preserves traceable word timing and labels conservative edit candidates. Versioned edit plans capture user goals and structured keep/delete decisions without source timestamps, and integrity validation rejects unknown, duplicate, missing, conflicting, or dependency-breaking decisions. The deterministic RulePlanner produces reproducible plans with conservative, balanced, and aggressive policies while preserving user-required and context-required segments. LLM-assisted planning now has a replaceable provider, constrained prompts, strict validation, one controlled repair, bounded calls, safe errors, cooperative cancellation, and credential-free provenance. A concrete DeepSeek adapter uses `deepseek-v4-flash`; local analysis classifies target Segments, records importance and dependencies, merges overlapping judgments deterministically, falls back to content on classification conflicts, and preserves user-required or context-required material. Global planning describes a topic, opening, evidence-backed core points, and conclusion using only known Segment IDs, selects complete candidates toward the requested duration, explains unavoidable fallbacks, and reports pronoun, causal, or reference breaks after cuts. Approved keep decisions compile into a versioned Timeline with source-ordered clips, contiguous output ranges, and an exact estimated duration. Clip boundaries snap to their first and last words, support clamped non-overlapping padding, avoid partial neighboring words, and retain attached punctuation. Timeline post-processing merges nearby clips without losing Segment coverage, removes only unprotected short clips, records every repair reason, and reports likely jump cuts without mutating the result. Pre-render validation blocks structural, media-reference, and required-track errors while returning non-blocking risk diagnostics without changing the timeline. Deterministic FFmpeg argument construction supports exact single-clip cuts, validated multi-clip filter graphs, explicit output encoding and video normalization, and shell-independent local path handling. The renderer reports structured progress, handles cancellation and timeouts while reaping processes, preserves bounded FFmpeg error context, and publishes completed temporary outputs atomically without leaving failed artifacts. Audio rendering normalizes sample rate and channel layout, supports optional boundary fades, and measures excessive silence, clipping risk, and audio/video duration drift. Retained transcript words map onto edited time and export as validated, readable SRT with configurable line, duration, punctuation, and cut-boundary rules. A real generated-media integration test verifies playable synchronized MP4 and round-trippable subtitles. The workflow is exposed through end-to-end CLI commands.

That CLI exposure is now complete: the workflow is available as separate `init`, `transcribe`, `plan`, `render`, and read-only `inspect` commands. A resumable one-command workflow is also available through `minicut edit`.

## CLI workflow

```bash
minicut init ./my-project --project-id my-video
minicut transcribe ./my-project ./input.mov \
  --provider mlx --model large-v3-turbo
minicut plan ./my-project --asset-id <asset-id> --target-ms 60000 \
  --planner deepseek
minicut render ./my-project --asset-id <asset-id> --output ./result.mp4
minicut inspect ./my-project --asset-id <asset-id>
```

Use `--planner rule` for deterministic local planning. DeepSeek planning sends structured transcript text to the configured API, but never sends the original media.

Subtitles default to a selectable MP4 track. Use `render --subtitle-mode burned`
to put text into the video image. Burned output explicitly loads an installed CJK
font: Arial Unicode MS (or Heiti SC) on macOS, Microsoft YaHei on Windows, and
Noto Sans CJK SC in common Linux font locations. If no readable font is found,
the command explains how to configure one; it does not download fonts.

To use another installed font, set both variables before rendering:

```bash
export MINICUT_SUBTITLE_FONT_PATH="/absolute/path/NotoSansCJKsc-Regular.otf"
export MINICUT_SUBTITLE_FONT_NAME="Noto Sans CJK SC"
```

The name must match the font's family, and the selected font must cover your
subtitle characters. System fonts are not bundled or redistributed. Changing
the configured font causes burned output to be rendered again; previously
burned boxes cannot be repaired by changing player settings.

The same stages can be run in one resumable command:

```bash
minicut edit ./my-project ./input.mov \
  --provider mlx --model large-v3-turbo \
  --target-ms 60000 --planner deepseek --output ./result.mp4
```

Re-running the same command reuses valid transcription, plan, and render artifacts. Press Ctrl-C to request cooperative cancellation; completed artifacts remain available for the next run.

Review `.minicut/plans/<asset-id>.txt`, then override decisions without another model call:

```bash
minicut plan-edit ./my-project --asset-id <asset-id> \
  --restore <segment-id> --delete <segment-id> \
  --output ./result-revised.mp4
```

Plan revisions are retained under `.minicut/plans/<asset-id>-history/`. A valid change increments the plan revision and forces timeline recompilation and rendering for the requested output.

## Local API

Point the API at a directory whose immediate children are MiniCut projects, then start the local-only server:

```bash
MINICUT_PROJECTS_ROOT=/path/to/projects uv run minicut-api
```

Interactive API documentation is available at `http://127.0.0.1:8000/docs`. The API supports project management, idempotent background transcription/planning/rendering tasks, plan review and revision, and byte-range streaming for registered source media and project exports. It never accepts an arbitrary source filesystem path for media playback.

Start the local review interface in a second terminal:

```bash
cd web
npm install
npm run dev
```

Open `http://127.0.0.1:5173/` to list projects, create one by name, and switch projects without entering IDs. Inside a project, choose a media file and click import: the browser copies it to the local project, leaving the original unchanged. The library shows filename, duration, and transcription status. This transfers the file to the local API, not to the LLM; unlike CLI path registration, it needs space for a copy.

Expand the media's transcription settings, select MLX (Apple Silicon) or PyTorch Whisper, a model, and Chinese or English, then start transcription. Install the chosen backend first. Existing Hugging Face model caches are shared; start the API with `HF_HUB_OFFLINE=1` to use cached MLX models offline. Refreshing or returning to a project recovers its latest task. Stopping status queries does **not** cancel backend computation. After a process restart, interrupted tasks become resumable failures. Use Resume to continue from saved chunks; work does not restart automatically. Cancel is cooperative: a running model/chunk finishes before cancellation is acknowledged.

The dark workbench keeps the current asset and candidates on the left, one player in the center, and Generate/Edit/Export tabs on the right. Selecting a candidate opens Edit directly; Generate remains available for a new selection. Settings and concise explanations fold away; panels scroll independently and switching tabs preserves drafts.

For a transcribed asset, select a highlight preset, enter custom instructions, and set count, duration limits, source overlap, and an optional original-speech hook. Start the API with `uv run --env-file .env minicut-api` to load your local DeepSeek configuration. Generation sends transcript text, not video, and may incur API charges. Each generation creates a separate collection; the project page recovers the latest generation. Select candidates to persist a shortlist or show selected items only.

Selecting a candidate automatically renders a low-resolution H.264 preview with burned subtitles. Playback starts at zero in the edited video, including reordered opening quotes. The preview is reused for the same saved version; edits generate a new version without displaying the old video as current. Preview generation does not call the LLM. Failed previews can be retried. Source-time jump buttons explicitly switch the single player to the original asset for inspection; use Return to Preview to switch back. Subtitle corrections and reversible instance deletion are available under Edit. Corrections do not change source words or speech. Save subtitle drafts separately from keep/delete changes. At least one body instance must remain.

Expand the clip-order controls to move instances or mark an original-speech opening quote. Hooks precede body clips. Version history is read-only and starts when history recording is enabled. In the workspace, choose soft or burned subtitles and optional audio fades or FFmpeg denoising, then export the current output. Audio processing defaults to off. On the candidate page, select videos and click batch export: outputs run sequentially with independent statuses and downloads; a failed output can be retried without rerendering successful ones. Refresh recovers the latest export per output. Every export request retains independent files and does not call the LLM. Interrupted exports can be retried independently after a restart; successful exports remain available.

Export settings support original, 16:9, 9:16, 1:1 and 4:5 ratios at 720 or 1080 tiers. Original preserves the source display ratio without upscaling, with a longest-edge limit of 1280 or 1920 and even dimensions. Fixed ratios use 1280×720 / 1920×1080, 720×1280 / 1080×1920, 720×720 / 1080×1080, or 720×900 / 1080×1350. Default fitting preserves the whole frame with borders; optional center cropping fills the frame without stretching or person tracking and may remove edge content or existing source subtitles. Burned subtitle layout adapts to the output shape. Batch geometry can be set once or overridden for individual selected outputs. Settings apply to the next request; refresh restores export results, not unsent settings drafts.

Existing plan review links (`?project=<project-id>&asset=<asset-id>`) remain supported. The review screen shows every keep/delete decision and its reason, previews the compiled cut without rendering, marks cut points and jump-cut risks, persists restore/delete changes, supports undo, and updates the estimated output duration. It can then start a formal render and download the project-owned video and subtitle. With a segment focused, use `K` to keep, `D` to delete, and Space to play or pause.

A local end-to-end check used the 14-minute-48-second [Steve Wozniak interview](https://commons.wikimedia.org/wiki/File:Interview_with_Steve_Wozniak.webm) by The Conversation / ConversationEDU ([CC BY 3.0](https://creativecommons.org/licenses/by/3.0/)). English MLX transcription, two DeepSeek-selected excerpts, versioned previews, subtitle correction, and batch 720p exports completed. Edited outputs were approximately 65.5 and 104.5 seconds; changes include excerpt selection, reordered original-speech openings, added subtitles, and resizing. These test media are not bundled. Excerpt quality still needs human review; an original-speech hook can be a question or exceed five seconds to preserve a complete sentence.

## Long videos, recovery, and usage

Media longer than ten minutes uses five-minute, mono 16 kHz audio chunks with two-second overlap. Each successful chunk is saved with the existing source/model/language cache identity. MLX uses the shared Hugging Face cache, including models downloaded by another project; no project-specific model download is needed when that model is already cached.

Long highlight requests use overlapping source chapters, neutral chapter candidates, global selection, and refinement against original source IDs. Changing the brief reuses identical successful chapter requests locally. DeepSeek prefix caching is separate and best-effort. The project activity panel shows task states and actual input/output/cache tokens; missing metrics or prices remain unknown. Malformed JSON has one format-repair attempt, and invalid durations have one semantic revision. The application can return fewer candidates or none instead of silently cutting necessary context.

The API permits one heavy task at a time per process. Transcription, model analysis, preview, and exports share this queue. Run one API process per project root. Cancellation is acknowledged at chunk/request boundaries; a response that has already completed is saved before cancellation. SQLite request receipts and chunk files support explicit resume after failure/restart. A request interrupted before its response was saved may need another paid call; its provider-side charge cannot be inferred locally.

Optional price configuration uses USD per million tokens: `MINICUT_PRICE_HIT_USD_PER_MILLION`, `MINICUT_PRICE_MISS_USD_PER_MILLION`, and `MINICUT_PRICE_OUTPUT_USD_PER_MILLION`, with `MINICUT_PRICE_SOURCE` and `MINICUT_PRICE_DATE`. Estimates are not invoices. Do not assume the example/test price applies to another model or date.

For a separate test server, keeping the existing server untouched:

```bash
MINICUT_PROJECTS_ROOT="$PWD/manual-test/web-projects" \
MINICUT_API_PORT=8001 HF_HUB_OFFLINE=1 \
uv run --env-file .env minicut-api
```

In a second terminal, run `cd web` then `MINICUT_API_URL=http://127.0.0.1:8001 npm run dev -- --host 127.0.0.1`.

A real 64m47s [Wikidata workshop](https://commons.wikimedia.org/wiki/File:Wikidata_Workshop_-_Theoretical_part_-_Maastricht_University_-_15_October_2024.webm) by Olaf Janssen ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)) was tested on an Apple M5 / 24 GiB Mac. Offline MLX produced 8,343 words in 13 saved chunks. Eight chapters yielded two excerpts of 82.94s and 96.78s. Browser editing and batch 720p portrait/landscape burned-subtitle exports completed, followed by a square soft-subtitle export. Changes to the source are excerpt selection, resizing/padding, added subtitles, and a Chinese terminology annotation. Test media and generated outputs are not bundled.

Actual model receipts totaled 49,889 input and 7,496 output tokens, including 9,600 server-cache-hit input tokens. Fourteen paid requests, including failed selection/format repair work, were estimated at US$0.02114 using the recorded test prices. A changed brief reused nine local responses and made two additional requests. The new render path removed measured cumulative audio drift: source correlation at the start/middle/end of both excerpts gave approximately -1ms offsets. Maximum measured stream-duration difference was 47ms. The square render took 10.06s, with sampled API-plus-FFmpeg RSS up to 2.42 GiB. These are sample-specific results, not performance guarantees.

Limits: chapter/final-input budgets are conservative character estimates (18k/42k), not tokenizer counts. An indivisible source segment or required context exceeding the chapter budget is explicitly rejected; automatic semantic splitting of that pathological input remains unfinished. Chapter discovery can miss an angle requested later, and does not replace complete long-form speech cleanup. Transcription may misrecognize negations; original speech and display subtitle corrections must be reviewed before publication. This run verifies the technical workflow and excerpt source mapping, not independent human editorial approval. Windows/Linux and long PyTorch inference were not exercised.

## Development

Create or update the local environment, then run the complete quality gate:

```bash
uv sync
uv run python tools/check.py
cd web && npm test && npm run build
```

Real MLX inference is opt-in so the default test suite never downloads or loads a model. In an environment that provides `mlx-whisper`, point the integration test at a local media file:

```bash
MINICUT_MLX_INTEGRATION_MEDIA=/path/to/media.mov \
  python -m pytest tests/integration/test_mlx_whisper_integration.py
```

To configure DeepSeek locally, copy `.env.example` to the ignored `.env` file and set `DEEPSEEK_API_KEY`. The defaults select `deepseek-v4-flash` at `https://api.deepseek.com`. Application code can then create the configured planner with `create_deepseek_planner_from_env`; load the local file when starting Python:

```bash
uv run --env-file .env python
```

Never commit `.env`; only `.env.example` belongs in version control.

## Development principles

- Build one testable behavior at a time.
- Require unit tests for every executable behavior.
- Keep model providers and media engines replaceable.
- Keep edit decisions explainable, reversible, and reproducible.
- Run locally by default; make cloud processing an explicit choice.
