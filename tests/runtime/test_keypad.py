from romtest import run_test

SCRIPT = (
    "--press", "5:A", "--press", "10:A+B", "--press", "15:none", "--press", "20:A",
    "--press", "25:A+B",
)


def test_keyinput_and_the_keypad_interrupt_follow_the_keys():
    run_test("keypad", args=SCRIPT).assert_passed()


def test_a_key_press_wakes_a_stopped_game():
    run = run_test("stop_wake", args=("--press", "30:START"))
    run.assert_passed()
    assert run.lines[:2] == ("stopping", "woke")


def test_a_stopped_game_that_nothing_wakes_ends_the_run():
    run = run_test("stop_wake")
    assert run.status == 0
    assert run.lines == ("stopping",)


def test_presses_must_name_keys_and_come_in_order():
    for script in (("--press", "3:JUMP"), ("--press", "9:A", "--press", "4:B"), ("--press", "A")):
        run = run_test("stop_wake", args=script)
        assert run.status == 2
        assert "usage:" in run.stderr


def test_a_key_held_from_the_start_requests_the_interrupt_once_keycnt_asks():
    run = run_test("stop_wake", args=("--press", "0:START"))
    run.assert_passed()  # the request came with the KEYCNT write: the Stop wakes at once
    assert run.lines[:2] == ("stopping", "woke")
