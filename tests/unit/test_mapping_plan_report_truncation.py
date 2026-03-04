from __future__ import annotations

from hdt_mapping_plan.validate import CriticIssue, CriticReport, merge_reports
from hdt_mapping_plan import errors as E


def test_merge_reports_truncates() -> None:
    reports = [
        CriticReport(
            ok=False,
            errors=[CriticIssue(code="X", path=f"/e/{i}", detail="d") for i in range(200)],
            warnings=[],
        )
    ]
    rep = merge_reports(reports, profile={"critic": {"max_errors": 10, "max_warnings": 10}})
    assert len(rep.errors) == 10
    assert any(w.code == E.REPORT_TRUNCATED for w in rep.warnings)
