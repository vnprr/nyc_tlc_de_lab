"""Calendar coverage rules shared by taxi processing and analytics."""

from src.config import parse_period


def shift_period(period: str, months: int) -> str:
    """Shift an exact ``YYYY-MM`` value without depending on run time."""
    year, month = parse_period(period)
    shifted = year * 12 + month - 1 + months
    shifted_year, zero_based_month = divmod(shifted, 12)
    if not 1 <= shifted_year <= 9999:
        raise ValueError("Shifted period is outside the supported calendar")
    return f"{shifted_year:04d}-{zero_based_month + 1:02d}"


def required_source_periods(event_period: str) -> tuple[str, str, str]:
    """Return source months needed for one complete event-time partition."""
    return (
        shift_period(event_period, -1),
        event_period,
        shift_period(event_period, 1),
    )


def publishable_periods(source_periods: tuple[str, ...]) -> tuple[str, ...]:
    """Return months whose previous, current and next sources are present."""
    if not source_periods:
        raise ValueError("source_periods must not be empty")
    for period in source_periods:
        parse_period(period)
    if len(source_periods) != len(set(source_periods)):
        raise ValueError("source_periods must not contain duplicates")
    if source_periods != tuple(sorted(source_periods)):
        raise ValueError("source_periods must be in chronological order")

    available = set(source_periods)
    return tuple(
        period
        for period in source_periods
        if set(required_source_periods(period)).issubset(available)
    )
