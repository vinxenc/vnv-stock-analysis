"""See a dividend / split adjustment in the bars a source returns, against the bars already stored (option B of the
price adjustment: the stored history is adjusted in place, each adjustment logged in `vn_stock_price_adjustments`).

The sources quote their whole history adjusted as of the day of the fetch, while `vn_stock_prices` keeps each bar as it
was fetched. After an ex-date (and DNSE already after midnight on its eve) the source's older bars are the stored ones
times one factor `f` < 1, with the same volume: the sources adjust prices only, so the volume is never scaled here
either. `detect` finds that pattern on the bars both have, from the same source (at least two of them); the store then
multiplies every stored bar up to the last changed one by `f`.
"""

import datetime as dt
from dataclasses import dataclass

from libs.db.models import Price

GRID = 0.01  # the sources quote thousand VND with 2 decimals: a smaller difference is rounding, not an adjustment
PRICES = ("open", "high", "low", "close")


class InconsistentBars(ValueError):
    """The source's bars differ from the stored ones, but not by one factor on a run of the oldest bars with an equal
    volume: nothing is adjusted, a person looks at it."""


@dataclass(frozen=True)
class Adjustment:
    symbol: str
    source: str
    through: dt.date  # the last date whose stored bar is multiplied; the ex-date is a later session
    factor: float
    fetched: list[Price]  # the source's bars up to `through`: they replace the stored ones as they are


def moved(fetched: Price, stored: Price) -> bool:
    return any(abs(getattr(fetched, name) - getattr(stored, name)) > GRID / 2 for name in PRICES)


def _fits(fetched: Price, stored: Price, factor: float) -> bool:
    return all(abs(getattr(fetched, name) - getattr(stored, name) * factor) <= GRID for name in PRICES)


def detect(fetched: list[Price], stored: dict[dt.date, Price]) -> Adjustment | None:
    """`fetched`: one symbol's bars from one source, ascending, the latest last. `stored`: that symbol's stored bars by
    date. The run is read from the bars stored from the same source (another source may adjust differently or not at
    all). The latest bar is left out when its volume differs: that is a correction of the day (a bar fetched before the
    close), which the store upserts anyway. An older moved bar with another volume is a bar stored before the close: it
    is no evidence, but the source's bar replaces it. The factor needs at least two moved bars with an equal volume,
    and every one of them must fit it. A later bar stored from another source that fits the factor is adjusted too.
    Returns None when nothing moved; raises InconsistentBars when the moves are not one adjustment."""
    pairs = [(bar, stored[bar.date]) for bar in fetched if bar.date in stored and stored[bar.date].source == bar.source]
    if pairs and pairs[-1][0] is fetched[-1] and pairs[-1][0].volume != pairs[-1][1].volume:
        pairs = pairs[:-1]
    flags = [moved(bar, old) for bar, old in pairs]
    if not any(flags):
        return None
    symbol = fetched[-1].symbol
    last = max(index for index, flag in enumerate(flags) if flag)
    changed = pairs[: last + 1]
    if not all(flags[: last + 1]):
        raise InconsistentBars(f"{symbol}: bars moved with unchanged ones between them")
    evidence = [(bar, old) for bar, old in changed if bar.volume == old.volume]
    if len(evidence) < 2:
        raise InconsistentBars(f"{symbol}: {len(evidence)} moved bar(s) with an equal volume, too few for a factor")
    factor = sum(bar.close for bar, _ in evidence) / sum(old.close for _, old in evidence)
    for bar, old in evidence:
        if not _fits(bar, old, factor):
            raise InconsistentBars(f"{symbol}: {bar.date} does not fit the factor {factor:.4f}")
    through, replaced = changed[-1][0].date, [bar for bar, _ in changed]
    for bar in fetched:  # e.g. the latest session stored from VPS on a day DNSE failed
        old = stored.get(bar.date)
        if bar.date <= through or old is None:
            continue
        if old.source == bar.source or not moved(bar, old) or not _fits(bar, old, factor):
            break
        through = bar.date
        replaced.append(bar)
    return Adjustment(symbol, fetched[-1].source, through, factor, replaced)
