import pytest

from src.coverage import publishable_periods


def test_only_interior_month_has_complete_event_time_coverage():
    assert publishable_periods(("2024-01", "2024-02", "2024-03")) == ("2024-02",)


def test_two_edge_months_publish_three_interior_months_across_year_boundary():
    assert publishable_periods(("2023-12", "2024-01", "2024-02", "2024-03", "2024-04")) == (
        "2024-01",
        "2024-02",
        "2024-03",
    )


def test_duplicate_source_period_is_rejected():
    with pytest.raises(ValueError, match="duplicates"):
        publishable_periods(("2024-01", "2024-02", "2024-02", "2024-03"))
