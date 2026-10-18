from romtest import run_test


def test_timers():
    run_test("timers").assert_passed()


def test_rewriting_a_running_timer_keeps_its_overflows():
    run_test("timer_rewrite").assert_passed()
