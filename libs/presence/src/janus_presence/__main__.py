"""python -m janus_presence CLI (SPEC.md ampliación, requisito 39).

    python -m janus_presence run --config presence.toml
    python -m janus_presence visits --config presence.toml [--since 24h] [--last 20] [--json]

`run` loads the config, builds the runner and blocks until Ctrl+C or SIGTERM.
`visits` reads the event log the runner wrote and lists who came and went, so
it works with the runner running or stopped (requisito 47).
The CLI holds no perception logic. Its job is to turn the failures an operator
can act on (a bad config, a busy port, a missing key or model) into one line on
stderr and an exit code, and to say where the review page is. Any other
exception is a bug and keeps its traceback.

Exit codes: 0 after a clean stop, 1 when the runner could not start or stopped
on one of those failures, 2 when the command line or the config file is wrong
(argparse uses 2 for usage errors too).
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from janus_biometrics import BiometricsError

from janus_presence.errors import PresenceError
from janus_presence.runner import PresenceRunner, build_runner, run_until_signal
from janus_presence.runner_config import RunnerConfig, RunnerConfigError, load_runner_config
from janus_presence.visit_report import (
    log_paths,
    parse_duration,
    read_labels,
    read_visits,
    render_json,
    render_visits,
    select_visits,
)

__all__ = ["EXIT_FAILURE", "EXIT_OK", "EXIT_USAGE", "build_parser", "main"]

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2

# The module runs as `__main__` under `python -m`, so the logger is named
# explicitly to keep its lines readable.
_log = logging.getLogger("janus_presence.cli")

_LOG_LEVELS = ("debug", "info", "warning", "error")
_DEFAULT_LOG_LEVEL = "info"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# What an operator can fix: presence and biometrics own errors (a missing key,
# a model that cannot be fetched, a camera that is not there) and OS errors
# (a port already in use, an unreadable state directory).
_OPERATOR_ERRORS = (PresenceError, BiometricsError, OSError)


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format=_LOG_FORMAT)


def _fail(error: Exception, exit_code: int) -> int:
    print(f"Error: {error}", file=sys.stderr)
    return exit_code


def _announce(runner: PresenceRunner, config: RunnerConfig) -> None:
    """Says what is about to run and where the review page is. The token
    itself is never printed, only the file that holds it."""
    enabled = [entry.source_id for entry in config.sources if entry.enabled]
    _log.info("starting the presence runner with sources: %s", ", ".join(enabled))
    if runner.review_url is None:
        _log.info("the review page is disabled in the config")
        return
    _log.info(
        "review page at %s (log in with the token stored in %s)",
        runner.review_url,
        config.review_token_path(),
    )


def _cmd_run(args: argparse.Namespace) -> int:
    _configure_logging(args.log_level)
    try:
        config = load_runner_config(args.config)
    except RunnerConfigError as exc:
        return _fail(exc, EXIT_USAGE)
    try:
        runner = build_runner(config)
        _announce(runner, config)
        run_until_signal(runner)
    except _OPERATOR_ERRORS as exc:
        return _fail(exc, EXIT_FAILURE)
    return EXIT_OK


def _cmd_visits(args: argparse.Namespace) -> int:
    _configure_logging("warning")
    try:
        config = load_runner_config(args.config)
    except RunnerConfigError as exc:
        return _fail(exc, EXIT_USAGE)
    try:
        rows = read_visits(log_paths(config.event_log_path()))
    except OSError as exc:
        return _fail(exc, EXIT_FAILURE)
    since = datetime.now(UTC) - args.since if args.since is not None else None
    rows = select_visits(rows, since=since, last=args.last)
    labels = read_labels(config.state_dir / "presence" / "presence.db")
    print(render_json(rows, labels) if args.json else render_visits(rows, labels))
    return EXIT_OK


def _duration_arg(text: str) -> timedelta:
    try:
        return parse_duration(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _positive_int(text: str) -> int:
    try:
        number = int(text)
    except ValueError:
        number = 0
    if number <= 0:
        raise argparse.ArgumentTypeError(f"'{text}' is not a positive whole number")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m janus_presence")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run the autonomous presence runner")
    run.add_argument("--config", type=Path, required=True, help="Runner TOML config file")
    run.add_argument("--log-level", choices=_LOG_LEVELS, default=_DEFAULT_LOG_LEVEL)
    run.set_defaults(func=_cmd_run)

    visits = subparsers.add_parser("visits", help="List who came and went, from the event log")
    visits.add_argument("--config", type=Path, required=True, help="Runner TOML config file")
    visits.add_argument(
        "--since",
        type=_duration_arg,
        help="only visits that started this long ago or later: 90m, 12h or 7d",
    )
    visits.add_argument("--last", type=_positive_int, help="only the newest N visits")
    visits.add_argument("--json", action="store_true", help="print JSON instead of a table")
    visits.set_defaults(func=_cmd_visits)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
