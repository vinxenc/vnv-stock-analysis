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
    assert (adjustment.through, adjustment.source) == (D[4], "DNSE")
    assert adjustment.factor == pytest.approx(0.9858, abs=1e-4)
    assert adjustment.fetched == fetched[:5]


def test_an_eve_run_adjusts_the_latest_bar_too() -> None:
    """DNSE after midnight on the eve: the latest bar, stored raw at 19:00, comes back adjusted with the same volume."""
    fetched = [bar(D[i], CLOSES[i], factor=0.9775) for i in range(5)]
    adjustment = detect(fetched, stored(0, 1, 2, 3, 4))
    assert adjustment is not None and adjustment.through == D[4]


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
    assert adjustment is not None and adjustment.through == D[3]


@pytest.mark.parametrize(
    ("fetched", "message"),
    [
        ([bar(D[0], CLOSES[0]), bar(D[1], CLOSES[1], factor=0.9), bar(D[2], CLOSES[2])], "unchanged ones between"),
        ([bar(D[0], CLOSES[0], factor=0.9, volume=5), bar(D[1], CLOSES[1]), bar(D[2], CLOSES[2])], "another volume"),
        ([bar(D[0], CLOSES[0], factor=0.9), bar(D[1], CLOSES[1], factor=0.95), bar(D[2], CLOSES[2])], "does not fit"),
    ],
    ids=["a gap", "a volume", "two factors"],
)
def test_moves_that_are_not_one_adjustment(fetched: list[Price], message: str) -> None:
    with pytest.raises(InconsistentBars, match=message):
        detect(fetched, stored(0, 1, 2))


def test_a_factor_must_be_positive(engine: Engine) -> None:
    """`alembic check` ignores CHECK constraints: Postgres itself must refuse a factor of 0."""
    row = {"symbol": "BVH", "through": D[0], "factor": 0.0, "source": "DNSE", "bars": 1}
    with pytest.raises(IntegrityError, match="ck_vn_stock_price_adjustments_factor"), engine.begin() as connection:
        connection.execute(insert(PriceAdjustment), [row])
