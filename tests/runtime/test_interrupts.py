from romtest import run_test


def test_scanlines_interrupts_and_waits():
    run_test("interrupts").assert_passed()


def test_soft_reset_from_an_interrupt_handler():
    run_test("reset_in_irq").assert_passed()


def test_interrupt_waits_turn_ime_on_on_every_pass():
    run_test("intrwait_ime", frames=60).assert_passed()


def test_an_interrupt_without_a_handler_is_an_error():
    run = run_test("err_no_handler")
    assert run.status == 3
    assert "no handler is set at 0x03007FFC" in run.stderr
