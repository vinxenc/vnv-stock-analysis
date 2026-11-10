"""Indicators #22-#24: the ones that look for a shape (divergence, candle pattern, trendline), not for a number.

They return a `Detection`: a strength between 0 and 1 and the facts behind it, or 0.0 when nothing was found.
Positions are sessions ago (0 = today). Every definition is in docs/plans/phase-1-sql-screens.md ("Definitions").
"""

import math
from itertools import combinations

from libs.analysis.features import Candles, Detection, mean
from libs.indicators import Indicators

PIVOT_SPAN = 3  # a pivot is lower / higher than this many sessions on each side, so it is confirmed 3 sessions late


def pivot_lows(values: list[float], span: int = PIVOT_SPAN) -> list[int]:
    """Indexes whose value is strictly below the `span` values before and the `span` after."""
    return [
        index
        for index in range(span, len(values) - span)
        if all(values[index] < values[index + offset] for offset in range(-span, span + 1) if offset)
    ]


def pivot_highs(values: list[float], span: int = PIVOT_SPAN) -> list[int]:
    """Indexes whose value is strictly above the `span` values before and the `span` after."""
    return [
        index
        for index in range(span, len(values) - span)
        if all(values[index] > values[index + offset] for offset in range(-span, span + 1) if offset)
    ]


def _share(value: float, start: float, end: float) -> float:
    """Linear 0 at `start`, 1 at `end`, clamped (`start > end` for a falling ramp)."""
    return min(1.0, max(0.0, (value - start) / (end - start)))


# #22 RSI bullish divergence

DIVERGENCE_WINDOW = 40  # both pivot lows must lie in the last 40 sessions
DIVERGENCE_GAP = 5  # sessions between the two pivot lows, at least
DIVERGENCE_DROP = 0.01  # the later low must be at least 1% lower in price
DIVERGENCE_RSI_CEILING = 45  # the earlier low must come from a weak RSI
DIVERGENCE_RSI_GAP = 8  # RSI points of improvement that earn the full strength


def rsi_divergence(candles: Candles, engine: Indicators) -> Detection | float:
    """Regular bullish divergence: price makes a lower low while RSI makes a higher low, and both have turned up.

    L2 = the latest pivot low (on close) in the window, L1 = the latest pivot low at least 5 sessions before it.
    Strength = RSI improvement over 0..8 points x recency (full while L2 is within 10 sessions, 0 at 25).
    """
    close, count = candles.close, len(candles)
    rsi = engine.rsi(close)
    lows = [index for index in pivot_lows(close) if index >= count - DIVERGENCE_WINDOW]
    if not lows:
        return 0.0
    second = lows[-1]
    earlier = [index for index in lows if second - index >= DIVERGENCE_GAP]
    if not earlier:
        return 0.0
    first = earlier[-1]
    rsi_first, rsi_second, rsi_now = rsi[first], rsi[second], rsi[-1]
    if rsi_first is None or rsi_second is None or rsi_now is None:
        return 0.0
    found = (
        close[second] <= close[first] * (1 - DIVERGENCE_DROP)
        and rsi_second > rsi_first
        and rsi_first <= DIVERGENCE_RSI_CEILING
        and close[-1] > close[second]
        and rsi_now > rsi_second
    )
    if not found:
        return 0.0
    strength = _share(rsi_second - rsi_first, 0, DIVERGENCE_RSI_GAP) * _share(count - 1 - second, 25, 10)
    details = {
        "l1_sessions_ago": count - 1 - first,
        "l1_rsi": rsi_first,
        "l2_sessions_ago": count - 1 - second,
        "l2_rsi": rsi_second,
    }
    return Detection(strength, details)


# #23 bullish reversal candle pattern

PATTERN_STRENGTH = {"engulfing": 1.0, "morning_star": 1.0, "piercing": 0.8, "hammer": 0.7}
PATTERN_RECENCY = (1.0, 0.6, 0.3)  # completed today, one session ago, two sessions ago
PATTERN_CONTEXT = -0.03  # the 5 sessions before the last candle must have fallen at least 3%
VOLUME_WINDOW = 20


def candle_pattern(candles: Candles, engine: Indicators) -> Detection | float:
    """The strongest bullish reversal pattern completed in the last 3 sessions, after a fall.

    Strength = pattern weight x recency x (1.0 if the last candle's volume >= 1.2x the average of the 20 sessions before
    it, else 0.6). Patterns come from the engine, with its own definitions. A candle with no range is skipped.
    """
    flags = engine.bullish_patterns(candles.open, candles.high, candles.low, candles.close)
    best: float = 0.0
    found: dict[str, float | int | str | None] = {}
    for sessions_ago, recency in enumerate(PATTERN_RECENCY):
        index = len(candles) - 1 - sessions_ago
        if candles.high[index] == candles.low[index]:
            continue
        if candles.close[index - 1] / candles.close[index - 6] - 1 > PATTERN_CONTEXT:
            continue
        average = mean(candles.volume[index - VOLUME_WINDOW : index])
        volume_factor = 1.0 if average and candles.volume[index] >= 1.2 * average else 0.6
        for name, weight in PATTERN_STRENGTH.items():
            strength = weight * recency * volume_factor
            if flags[name][index] and strength > best:
                best, found = strength, {"pattern": name, "sessions_ago": sessions_ago}
    return Detection(best, found) if best else 0.0


# #24 descending trendline breakout

LINE_WINDOW = 60  # sessions the line is built and checked on, ending 3 sessions before today
LINE_MIN_GAP = 8  # sessions between the two anchor pivots, at least
LINE_TOLERANCE = 0.005  # no high may poke through the line by more than this
TOUCH_TOLERANCE = 0.01  # a pivot high this close to the line touches it
BREAKOUT_MARGIN = 0.01  # a breakout closes at least 1% above the line
BREAKOUT_MAX = 0.07  # and must not have run more than 7% above it
BREAKOUT_RECENCY = (1.0, 0.6, 0.3)  # broke out today, one session ago, two sessions ago


def _best_line(highs: list[float], pivots: list[int], end: int) -> tuple[int, int, int] | None:
    """(first anchor, second anchor, touches) of the best valid falling line, or None.

    Valid: falling, anchors at least LINE_MIN_GAP apart, and no high between the first anchor and `end` above the line
    by more than LINE_TOLERANCE. Best: most touches, then the longest, then the most recent.
    """
    logs = [math.log(value) for value in highs]
    best: tuple[int, int, int] | None = None
    for first, second in combinations(pivots, 2):
        if second - first < LINE_MIN_GAP or logs[second] >= logs[first]:
            continue
        slope = (logs[second] - logs[first]) / (second - first)
        if any(
            logs[j] > logs[first] + slope * (j - first) + math.log(1 + LINE_TOLERANCE) for j in range(first, end + 1)
        ):
            continue
        touches = sum(
            abs(math.exp(logs[p] - (logs[first] + slope * (p - first))) - 1) <= TOUCH_TOLERANCE for p in pivots
        )
        if best is None or (touches, second - first, second) > (best[2], best[1] - best[0], best[1]):
            best = (first, second, touches)
    return best


def trendline_breakout(candles: Candles, engine: Indicators) -> Detection | float:
    """A close that just broke above a falling resistance line through two pivot highs.

    The line is built on the 60 sessions ending 3 before today (so a breakout cannot spoil its own line) and tested on
    the last 3 sessions. Strength = recency x (1.0 if the breakout volume >= 1.5x the 20-session average, else 0.6)
    x (1.0 for >= 3 touches, else 0.7).
    """
    highs, close, count = candles.high, candles.close, len(candles)
    end = count - 4  # the line ends 3 sessions before today
    start = end - LINE_WINDOW + 1
    pivots = [index for index in pivot_highs(highs) if start <= index <= count - 7]
    line = _best_line(highs, pivots, end)
    if line is None:
        return 0.0
    first, second, touches = line
    slope = (math.log(highs[second]) - math.log(highs[first])) / (second - first)

    def level(index: int) -> float:
        return math.exp(math.log(highs[first]) + slope * (index - first))

    broke = None  # the first session of the last 3 that closed 1% above the line after one that had not
    for sessions_ago in (2, 1, 0):
        index = count - 1 - sessions_ago
        above = close[index] >= level(index) * (1 + BREAKOUT_MARGIN)
        before = close[index - 1] < level(index - 1) * (1 + BREAKOUT_MARGIN)
        if above and before:
            broke = sessions_ago
            break
    now = level(count - 1)
    if broke is None or not now <= close[-1] <= now * (1 + BREAKOUT_MAX):
        return 0.0
    index = count - 1 - broke
    average = mean(candles.volume[index - VOLUME_WINDOW : index])
    volume_factor = 1.0 if average and candles.volume[index] >= 1.5 * average else 0.6
    strength = BREAKOUT_RECENCY[broke] * volume_factor * (1.0 if touches >= 3 else 0.7)
    details = {
        "anchor1_sessions_ago": count - 1 - first,
        "anchor2_sessions_ago": count - 1 - second,
        "line_today": now,
        "touches": touches,
        "broke_sessions_ago": broke,
    }
    return Detection(strength, details)
