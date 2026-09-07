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

The media-ingestion and local-project foundation is complete. MLX Whisper and open-source Whisper share the same validated Transcript v1 output contract, including word timestamps and absolute time across VAD chunks. Deterministic semantic segmentation preserves traceable word timing and labels conservative edit candidates. Versioned edit plans capture user goals and structured keep/delete decisions without source timestamps, and integrity validation rejects unknown, duplicate, missing, conflicting, or dependency-breaking decisions. The next step implements the deterministic RulePlanner, starting with explicit silence removal.

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

## Development principles

- Build one testable behavior at a time.
- Require unit tests for every executable behavior.
- Keep model providers and media engines replaceable.
- Keep edit decisions explainable, reversible, and reproducible.
- Run locally by default; make cloud processing an explicit choice.
