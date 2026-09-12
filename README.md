# MiniCut

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
call a language model. The existing CLI and Web review workflow still use
source-ordered keep/delete plans; multi-video Web controls are not connected yet.

Python highlight planning supports speech cleanup, podcast highlights,
opinion-first excerpts and knowledge digests, with explicit count, duration,
hook and natural-language requirements. A measured selection pass preserves
context and limits source overlap. At most one semantic revision can respond
to measured failures or explicit reviewer feedback; insufficient material is
reported rather than padded. Excerpts still need human review for meaning,
titles and transcription accuracy.

## Current status

The media-ingestion and local-project foundation is complete. MLX Whisper and open-source Whisper share the same validated Transcript v1 output contract, including word timestamps and absolute time across VAD chunks. Deterministic semantic segmentation preserves traceable word timing and labels conservative edit candidates. Versioned edit plans capture user goals and structured keep/delete decisions without source timestamps, and integrity validation rejects unknown, duplicate, missing, conflicting, or dependency-breaking decisions. The deterministic RulePlanner produces reproducible plans with conservative, balanced, and aggressive policies while preserving user-required and context-required segments. LLM-assisted planning now has a replaceable provider, constrained prompts, strict validation, one controlled repair, bounded calls, safe errors, cooperative cancellation, and credential-free provenance. A concrete DeepSeek adapter uses `deepseek-v4-flash`; local analysis classifies target Segments, records importance and dependencies, merges overlapping judgments deterministically, falls back to content on classification conflicts, and preserves user-required or context-required material. Global planning describes a topic, opening, evidence-backed core points, and conclusion using only known Segment IDs, selects complete candidates toward the requested duration, explains unavoidable fallbacks, and reports pronoun, causal, or reference breaks after cuts. Approved keep decisions compile into a versioned Timeline with source-ordered clips, contiguous output ranges, and an exact estimated duration. Clip boundaries snap to their first and last words, support clamped non-overlapping padding, avoid partial neighboring words, and retain attached punctuation. Timeline post-processing merges nearby clips without losing Segment coverage, removes only unprotected short clips, records every repair reason, and reports likely jump cuts without mutating the result. Pre-render validation blocks structural, media-reference, and required-track errors while returning non-blocking risk diagnostics without changing the timeline. Deterministic FFmpeg argument construction supports exact single-clip cuts, validated multi-clip filter graphs, explicit output encoding and video normalization, and shell-independent local path handling. The renderer reports structured progress, handles cancellation and timeouts while reaping processes, preserves bounded FFmpeg error context, and publishes completed temporary outputs atomically without leaving failed artifacts. Audio rendering normalizes sample rate and channel layout, supports optional boundary fades, and measures excessive silence, clipping risk, and audio/video duration drift. Retained transcript words map onto edited time and export as validated, readable SRT with configurable line, duration, punctuation, and cut-boundary rules. A real generated-media integration test verifies playable synchronized MP4 and round-trippable subtitles. The next step exposes the workflow through end-to-end CLI commands.

That CLI exposure is now complete: the workflow is available as separate `init`, `transcribe`, `plan`, `render`, and read-only `inspect` commands. The next step is a resumable one-command workflow.

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

Open `http://127.0.0.1:5173/` to list projects, create one by name, and switch projects without entering IDs. File import and transcription controls are not connected to this interface yet; use the CLI for those steps. Existing plan review links (`?project=<project-id>&asset=<asset-id>`) remain supported. The review screen shows every keep/delete decision and its reason, previews the compiled cut without rendering, marks cut points and jump-cut risks, persists restore/delete changes, supports undo, and updates the estimated output duration. It can then start a formal render and download the project-owned video and subtitle. With a segment focused, use `K` to keep, `D` to delete, and Space to play or pause.

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
