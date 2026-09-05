"""Allow MiniCut to run with ``python -m minicut``."""

from minicut.cli import main, run_cli

raise SystemExit(run_cli(main))
