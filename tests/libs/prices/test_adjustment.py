import datetime as dt

import pytest
from sqlalchemy import Engine, insert
from sqlalchemy.exc import IntegrityError

from libs.db.models import Price, PriceAdjustment
from libs.prices.adjustment import InconsistentBars, detect

D = [dt.date(2026, 11, d) for d in (19, 20, 21, 24, 25, 26)]


def bar(day: dt.date, close: float, volume: int = 1000, source: str = "DNSE", factor: float = 1.0) -> Price:
    """OHLC around `close`, all times `factor`, rounded to the source's 0.01 grid."""
    prices = {name: round(close * scale * factor, 2) for name, scale in (("open", 1.01), ("high", 1.02), ("low", 0.98))}
    return Price.model_validate(
        dict(symbol="BVH", source=source, date=day, close=round(close * factor, 2), volume=volume, **prices)
    )


CLOSES = [58.0, 57.6, 57.9, 57.2, 56.9, 55.0]


def stored(*days: int, factor: float = 1.0, source: str = "DNSE") -> dict[dt.date, Price]:
    return {D[i]: bar(D[i], CLOSES[i], source=source, factor=factor) for i in days}


def test_nothing_moved() -> None:
    assert detect([bar(day, close) for day, close in zip(D, CLOSES, strict=True)], stored(0, 1, 2, 3, 4)) is None


def test_an_ex_date_run_adjusts_every_older_bar() -> None:
    """The run on the ex-date (D[5]): the source's older bars are adjusted, the stored ones raw."""
    fetched = [bar(D[i], CLOSES[i], factor=0.9858) for i in range(5)] + [bar(D[5], CLOSES[5])]
    adjustment = detect(fetched, stored(0, 1, 2, 3, 4))
    assert adjustment is not None
    assert (adjustment.fetched[-1].date, adjustment.fetched[-1].source) == (D[4], "DNSE")
    assert adjustment.factor == pytest.approx(0.9858, abs=1e-4)
    assert adjustment.fetched == fetched[:5]


def test_an_eve_run_adjusts_the_latest_bar_too() -> None:
    """DNSE after midnight on the eve: the latest bar, stored raw at 19:00, comes back adjusted with the same volume."""
    fetched = [bar(D[i], CLOSES[i], factor=0.9775) for i in range(5)]
    adjustment = detect(fetched, stored(0, 1, 2, 3, 4))
    assert adjustment is not None and adjustment.fetched[-1].date == D[4]


def test_a_correction_of_the_latest_bar_is_not_an_adjustment() -> None:
    """A bar fetched before the close comes back final: another volume, the store upserts it."""
    fetched = [bar(D[i], CLOSES[i]) for i in range(4)] + [bar(D[4], 56.0, volume=2000)]
    assert detect(fetched, stored(0, 1, 2, 3, 4)) is None


def test_bars_of_another_source_are_not_compared() -> None:
    fetched = [bar(D[i], CLOSES[i], source="VPS", factor=0.95) for i in range(5)]
    assert detect(fetched, stored(0, 1, 2, 3, 4)) is None


def test_a_bar_already_adjusted_is_left_alone() -> None:
    """The first run after the deploy: BVH's bar of 2026-11-25 was already re-stored adjusted, the older ones not."""
    fetched = [bar(D[i], CLOSES[i], factor=0.9858) for i in range(6)]
    old = {**stored(0, 1, 2, 3), D[4]: bar(D[4], CLOSES[4], factor=0.9858)}
    adjustment = detect(fetched, old)
    assert adjustment is not None and adjustment.fetched[-1].date == D[3]


@pytest.mark.parametrize(
    ("fetched", "message"),
    [
        ([bar(D[0], CLOSES[0]), bar(D[1], CLOSES[1], factor=0.9), bar(D[2], CLOSES[2])], "unchanged ones between"),
        ([bar(D[0], CLOSES[0], factor=0.9, volume=5), bar(D[1], CLOSES[1]), bar(D[2], CLOSES[2])], "too few"),
        ([bar(D[0], CLOSES[0], factor=0.9), bar(D[1], CLOSES[1]), bar(D[2], CLOSES[2])], "too few"),
        ([bar(D[i], CLOSES[i]) for i in range(2)] + [bar(D[2], CLOSES[2], factor=0.9)], "unchanged ones between"),
        ([bar(D[0], CLOSES[0], factor=0.9), bar(D[1], CLOSES[1], factor=0.95), bar(D[2], CLOSES[2])], "does not fit"),
    ],
    ids=["a gap", "a volume", "one bar", "a lone latest bar", "two factors"],
)
def test_moves_that_are_not_one_adjustment(fetched: list[Price], message: str) -> None:
    with pytest.raises(InconsistentBars, match=message):
        detect(fetched, stored(0, 1, 2))


def test_a_lone_pair_is_no_factor() -> None:
    """VNDirect returns the latest bar alone: a re-quote with the same volume never rescales the whole history."""
    with pytest.raises(InconsistentBars, match="too few"):
        detect([bar(D[4], CLOSES[4], factor=0.98)], stored(4))


def test_a_bar_stored_before_the_close_is_replaced_not_evidence() -> None:
    """D[2] was stored at 14:45 with a partial volume and an earlier close: the source's final bar replaces it."""
    fetched = [bar(D[i], CLOSES[i], factor=0.9858) for i in range(5)] + [bar(D[5], CLOSES[5])]
    old = {**stored(0, 1, 3, 4), D[2]: bar(D[2], 57.5, volume=400)}
    adjustment = detect(fetched, old)
    assert adjustment is not None and adjustment.fetched[-1].date == D[4]
    assert adjustment.factor == pytest.approx(0.9858, abs=1e-4)
    assert adjustment.fetched == fetched[:5]


def test_a_later_bar_of_another_source_is_adjusted_too() -> None:
    """D[4] came from VPS on a day DNSE failed: it is raw as well, so it is multiplied and replaced."""
    fetched = [bar(D[i], CLOSES[i], factor=0.9858) for i in range(5)] + [bar(D[5], CLOSES[5])]
    adjustment = detect(fetched, {**stored(0, 1, 2, 3), **stored(4, source="VPS")})
    assert adjustment is not None and adjustment.fetched[-1].date == D[4]
    assert adjustment.fetched == fetched[:5]


def test_a_later_bar_of_another_source_that_does_not_fit_stops_the_run() -> None:
    fetched = [bar(D[i], CLOSES[i], factor=0.9858) for i in range(5)]
    adjustment = detect(fetched, {**stored(0, 1, 2, 3), **stored(4, source="VPS", factor=0.9858)})
    assert adjustment is not None and adjustment.fetched[-1].date == D[3]


def test_a_factor_must_be_positive(engine: Engine) -> None:
    """`alembic check` ignores CHECK constraints: Postgres itself must refuse a factor of 0."""
    row = {"symbol": "BVH", "through": D[0], "factor": 0.0, "source": "DNSE", "bars": 1}
    with pytest.raises(IntegrityError, match="ck_vn_stock_price_adjustments_factor"), engine.begin() as connection:
        connection.execute(insert(PriceAdjustment), [row])
