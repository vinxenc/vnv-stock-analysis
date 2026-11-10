"""The ranked report as a markdown table (the GitHub job summary)."""

from libs.analysis.models import AnalysisReport, SymbolResult, Theme


def _title(theme: Theme) -> str:
    return theme.value.replace("_", " ").capitalize()


def _row(rank: int, result: SymbolResult) -> str:
    score = "n/a" if result.score is None else f"{result.score:.1f}"
    cells = [str(rank), result.symbol, score, f"{result.coverage:.0f}"]
    cells += [f"{result.themes[theme]:.1f}" for theme in Theme]
    cells.append(", ".join(flag.value for flag in result.flags))
    return "| " + " | ".join(cells) + " |"


def render(report: AnalysisReport) -> str:
    """A header line (session, counts, sources) and one row per symbol in rank order. For reference only."""
    header = ["#", "Symbol", "Score", "Coverage"] + [_title(theme) for theme in Theme] + ["Flags"]
    scored = sum(result.score is not None for result in report.symbols)
    flagged = sum(bool(result.flags) for result in report.symbols)
    lines = [
        f"## VN stock screening score, session {report.as_of}",
        "",
        f"{len(report.symbols)} of {report.universe_size} symbols shortlisted: {scored} scored, "
        f"{len(report.symbols) - scored} with insufficient data, {flagged} flagged. "
        f"Sources: {', '.join(report.sources)}. A screening score, not a recommendation.",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    lines += [_row(rank, result) for rank, result in enumerate(report.symbols, start=1)]
    return "\n".join(lines) + "\n"
