"""Write the result of one pipeline job as `<directory>/<pipeline>.json`: {"level", "message", "pipeline"}.

Usage: python3 scripts/pipeline_state.py DIRECTORY PIPELINE JOB_STATUS SUCCESS_LEVEL SUCCESS_MESSAGE FAILURE_MESSAGE
JOB_STATUS is `${{ job.status }}`: success -> SUCCESS_LEVEL + SUCCESS_MESSAGE, cancelled -> warning, anything else
(failure) -> error + FAILURE_MESSAGE. scripts/notification.py reads these files.
Standard library only: the job may be writing this because `uv sync` itself failed.
"""
import argparse
import json
import sys
from pathlib import Path

LEVELS = ("info", "warning", "error")


def resolve(
    pipeline: str, job_status: str, success_level: str, success_message: str, failure_message: str
) -> dict[str, str]:
    if job_status == "success":
        level, message = success_level, success_message
    elif job_status == "cancelled":
        level, message = "warning", f"{pipeline} was cancelled"
    else:
        level, message = "error", failure_message
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}")
    return {"level": level, "message": message, "pipeline": pipeline}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("directory", "pipeline", "job_status", "success_level", "success_message", "failure_message"):
        parser.add_argument(name)
    args = parser.parse_args(argv)
    state = resolve(args.pipeline, args.job_status, args.success_level, args.success_message, args.failure_message)
    directory = Path(args.directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{args.pipeline}.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
