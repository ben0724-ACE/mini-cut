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

## Current status

The media-ingestion and local-project foundation is complete. MLX Whisper and open-source Whisper share the same validated Transcript v1 output contract, including word timestamps and absolute time across VAD chunks. Deterministic semantic segmentation preserves traceable word timing and labels conservative edit candidates. Versioned edit plans capture user goals and structured keep/delete decisions without source timestamps, and integrity validation rejects unknown, duplicate, missing, conflicting, or dependency-breaking decisions. The deterministic RulePlanner produces reproducible plans with conservative, balanced, and aggressive policies while preserving user-required and context-required segments. LLM-assisted planning now has a replaceable provider, constrained prompts, strict validation, one controlled repair, bounded calls, safe errors, cooperative cancellation, and credential-free provenance. A concrete DeepSeek adapter uses `deepseek-v4-flash`; local analysis classifies target Segments, records importance and dependencies, merges overlapping judgments deterministically, falls back to content on classification conflicts, and preserves user-required or context-required material. Global planning describes a topic, opening, evidence-backed core points, and conclusion using only known Segment IDs, selects complete candidates toward the requested duration, explains unavoidable fallbacks, and reports pronoun, causal, or reference breaks after cuts. Approved keep decisions compile into a versioned Timeline with source-ordered clips, contiguous output ranges, and an exact estimated duration. Clip boundaries snap to their first and last words, support clamped non-overlapping padding, avoid partial neighboring words, and retain attached punctuation. Timeline post-processing merges nearby clips without losing Segment coverage, removes only unprotected short clips, records every repair reason, and reports likely jump cuts without mutating the result. Pre-render validation now blocks structural, media-reference, and required-track errors while returning non-blocking risk diagnostics without changing the timeline. The next step builds deterministic FFmpeg commands.

## Development

Create or update the local environment, then run the complete quality gate:

```bash
uv sync
uv run python tools/check.py
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
