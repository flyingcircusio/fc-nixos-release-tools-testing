import itertools
from datetime import date, datetime
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

from auto_merge.config import (
    Config,
    GeneralConfig,
    MonitoringReviewConfig,
    PRMergeDayConfig,
)
from auto_merge.utils import (
    calculate_merge_date,
    convert_relative_day_to_date,
    next_production_merge,
    now_relative_day,
)


@pytest.fixture
def config():
    yield Config(
        pr_merge_days={
            0: PRMergeDayConfig(max_risk=5, min_urgency=1),
            1: PRMergeDayConfig(max_risk=4, min_urgency=1),
            2: PRMergeDayConfig(max_risk=3, min_urgency=2),
            3: PRMergeDayConfig(max_risk=2, min_urgency=3),
            4: PRMergeDayConfig(max_risk=1, min_urgency=5),
        },
        general=GeneralConfig(
            production_merge_day=3,
            production_merge_cutoff_hour=12,
            fc_nixos_repo_name="testing/testing",
            platform_versions=["24.11"],
        ),
        monitoring_review=MonitoringReviewConfig(
            name="platform-dev", notification_cutoff_hour=15
        ),
    )


@pytest.fixture
def now():
    """provides a UTC-bound mocked datetime definition of what is considered as
    'fc.directory.utils.now' in the tests"""
    with mock.patch("auto_merge.utils.now_tz") as now:
        now.return_value = datetime(
            2024, 11, 26, 15, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
        )
        yield now


def test_now_relative_day(config, now):
    # We want to test for microseconds, as these change equality in dateutil
    now.return_value = datetime(
        2024, 11, 21, 15, 10, 2, 41121, tzinfo=ZoneInfo("Europe/Berlin")
    )
    assert now_relative_day(config) == 0
    now.return_value = datetime(
        2024, 11, 22, 15, 12, 22, 12312, tzinfo=ZoneInfo("Europe/Berlin")
    )
    assert now_relative_day(config) == 1
    now.return_value = datetime(
        2024, 11, 25, 15, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )
    assert now_relative_day(config) == 2
    now.return_value = datetime(
        2024, 11, 26, 15, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )
    assert now_relative_day(config) == 3
    now.return_value = datetime(
        2024, 11, 27, 15, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )
    assert now_relative_day(config) == 4
    now.return_value = datetime(
        2024, 11, 28, 15, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )
    assert now_relative_day(config) == 0


def test_next_production_merge(config, now):
    # in the same week as the production merge
    assert next_production_merge(config) == datetime(
        2024, 11, 28, 12, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )

    # On the same day as the production merge before the cutoff
    now.return_value = datetime(
        2024, 11, 28, 10, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )
    assert next_production_merge(config) == datetime(
        2024, 11, 28, 12, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )

    # On the same day as the production merge after the cutoff
    now.return_value = datetime(
        2024, 11, 28, 14, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )
    assert next_production_merge(config) == datetime(
        2024, 12, 5, 12, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )

    # After the day of the production merge
    now.return_value = datetime(
        2024, 11, 29, 14, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )
    assert next_production_merge(config) == datetime(
        2024, 12, 5, 12, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )


def test_convert_relative_day_to_date_current_cycle(config, now):
    assert convert_relative_day_to_date(3, config) == date(2024, 11, 26)
    assert convert_relative_day_to_date(4, config) == date(2024, 11, 27)

    now.return_value = datetime(
        2024, 11, 28, 12, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )
    assert convert_relative_day_to_date(3, config) == date(2024, 12, 3)
    assert convert_relative_day_to_date(4, config) == date(2024, 12, 4)


def test_convert_relative_day_to_date_next_cycle(config, now):
    assert convert_relative_day_to_date(0, config) == date(2024, 11, 28)
    assert convert_relative_day_to_date(1, config) == date(2024, 11, 29)
    assert convert_relative_day_to_date(2, config) == date(2024, 12, 2)


def test_calculate_merge_date_part_week(config, now):
    # 2 days before release (day 3)
    # this cycle
    assert calculate_merge_date(risk=1, urgency=3, config=config) == date(
        2024, 11, 26
    )
    assert calculate_merge_date(risk=1, urgency=5, config=config) == date(
        2024, 11, 26
    )
    assert calculate_merge_date(risk=2, urgency=3, config=config) == date(
        2024, 11, 26
    )

    # next cycle
    assert calculate_merge_date(risk=2, urgency=2, config=config) == date(
        2024, 11, 28
    )
    assert calculate_merge_date(risk=1, urgency=1, config=config) == date(
        2024, 11, 28
    )
    assert calculate_merge_date(risk=5, urgency=2, config=config) == date(
        2024, 11, 28
    )

    # 1 day before release
    now.return_value = datetime(
        2024, 11, 27, 12, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )
    assert calculate_merge_date(risk=1, urgency=3, config=config) == date(
        2024, 11, 28
    )
    assert calculate_merge_date(risk=1, urgency=5, config=config) == date(
        2024, 11, 27
    )
    assert calculate_merge_date(risk=2, urgency=3, config=config) == date(
        2024, 11, 28
    )
    assert calculate_merge_date(risk=2, urgency=2, config=config) == date(
        2024, 11, 28
    )
    assert calculate_merge_date(risk=1, urgency=1, config=config) == date(
        2024, 11, 28
    )
    assert calculate_merge_date(risk=5, urgency=2, config=config) == date(
        2024, 11, 28
    )

    # Release Day
    # Now all PRs can be merged
    now.return_value = datetime(
        2024, 11, 28, 12, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
    )
    for risk, urgency in itertools.product(range(1, 5), range(1, 5)):
        assert calculate_merge_date(
            risk=risk, urgency=urgency, config=config
        ) == date(2024, 11, 28)


def test_merge_date_is_always_in_future(config, now):
    # 21: THU, 27: WED
    for day in [21, 22, 25, 26, 27]:
        now.return_value = datetime(
            2024, 11, day, 12, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")
        )
        for risk, urgency in itertools.product(range(1, 5), range(1, 5)):
            assert (
                calculate_merge_date(risk=risk, urgency=urgency, config=config)
                >= now.return_value.date()
            )
