import json
from pathlib import Path

from libs.analysis import summary
from libs.analysis.models import AnalysisReport

EXAMPLE = Path(__file__).parents[2] / "data" / "analysis_example.json"


def test_render_header_and_one_row_per_symbol_in_rank_order() -> None:
    report = AnalysisReport.model_validate(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    lines = summary.render(report).splitlines()
    assert lines[0] == "## VN stock screening score, session 2026-11-10"
    assert "2 of 406 symbols shortlisted: 1 scored, 1 with insufficient data, 2 flagged." in lines[2]
    assert "Sources: DNSE, VNDirect." in lines[2] and "not a recommendation" in lines[2]
    assert lines[4].startswith("| # | Symbol | Score | Coverage | Trend | Momentum | Money flow |")
    assert lines[4].endswith("| Flags |")
    assert lines[6] == "| 1 | HPG | 71.5 | 98 | 20.0 | 15.5 | 18.0 | 8.0 | 7.0 | 3.0 | ceiling_locked |"
    assert lines[7] == "| 2 | LPS | n/a | 62 | 5.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | low_coverage |"
    assert len(lines) == 8
