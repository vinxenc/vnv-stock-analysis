"""The ranked report as a markdown table (the GitHub job summary)."""

from libs.analysis.models import AnalysisReport, SymbolResult, Theme

THEMES = [(Theme.TREND, "Trend"), (Theme.MOMENTUM, "Momentum"), (Theme.MONEY_FLOW, "Money flow"),
          (Theme.POSITION, "Position"), (Theme.RISK, "Risk"), (Theme.REVERSAL, "Reversal")]  # fmt: skip


def _row(rank: int, result: SymbolResult) -> str:
    score = "n/a" if result.score is None else f"{result.score:.1f}"
    cells = [str(rank), result.symbol, score, f"{result.coverage:.0f}"]
    cells += [f"{result.themes[theme]:.1f}" for theme, _ in THEMES]
    cells.append(", ".join(flag.value for flag in result.flags))
    return "| " + " | ".join(cells) + " |"


def render(report: AnalysisReport) -> str:
    """A header line (session, counts, sources) and one row per symbol in rank order. For reference only."""
    header = ["#", "Symbol", "Score", "Coverage"] + [name for _, name in THEMES] + ["Flags"]
    lines = [
        f"## VN stock screening score, session {report.as_of}",
        "",
        f"{len(report.symbols)} of {report.universe_size} symbols shortlisted: {report.scored} scored, "
        f"{report.insufficient_data} with insufficient data, {report.flagged} flagged. "
        f"Sources: {', '.join(report.sources)}. A screening score, not a recommendation.",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    lines += [_row(rank, result) for rank, result in enumerate(report.symbols, start=1)]
    return "\n".join(lines) + "\n"
