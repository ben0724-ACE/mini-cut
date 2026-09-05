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

The project is in its foundation phase. Product contracts, quality gates, and the incremental delivery plan are being established before implementation begins.

## Development

Create or update the local environment, then run the complete quality gate:

```bash
uv sync
uv run python tools/check.py
```

## Development principles

- Build one testable behavior at a time.
- Require unit tests for every executable behavior.
- Keep model providers and media engines replaceable.
- Keep edit decisions explainable, reversible, and reproducible.
- Run locally by default; make cloud processing an explicit choice.
