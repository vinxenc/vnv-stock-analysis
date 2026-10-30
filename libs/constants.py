from datetime import timedelta, timezone

VN_TZ = timezone(timedelta(hours=7))  # Vietnam has no daylight saving time

# Script exit codes. Not 1: Python exits 1 on an uncaught error, which must not read as "no data".
# The workflows do not map them, any non-zero code fails the job.
NO_DATA = 4  # nothing to write or store, or too few symbols (MIN_COVERAGE): a partial outage is not a good run

MIN_COVERAGE = 0.9  # share of the symbols a run must fetch (or that must have a bar today) to count as complete
