def test_frozen_utc_clock_advances_without_local_timezone(
    frozen_utc_clock,
):
    before = frozen_utc_clock.now()
    frozen_utc_clock.advance(30)
    after = frozen_utc_clock.now()

    assert before.tzinfo is not None
    assert after.tzinfo is not None
    assert (after - before).total_seconds() == 30
    assert after.utcoffset().total_seconds() == 0
