import threading
import time

import pytest

from hlagents.gate import BACKGROUND, INTERACTIVE, VOICE, GateTimeout, ModelGate


def test_priority_order():
    gate, order = ModelGate(), []
    started = threading.Event()

    def holder():
        with gate.slot(BACKGROUND):
            started.set()
            time.sleep(0.3)

    def waiter(p):
        with gate.slot(p):
            order.append(p)

    h = threading.Thread(target=holder); h.start(); started.wait()
    threads = []
    for p in (BACKGROUND, VOICE, INTERACTIVE):
        t = threading.Thread(target=waiter, args=(p,)); t.start(); threads.append(t); time.sleep(0.05)
    for t in [h, *threads]:
        t.join()
    assert order == [VOICE, INTERACTIVE, BACKGROUND]


def test_one_at_a_time_and_timeout():
    gate = ModelGate()
    with gate.slot():
        with pytest.raises(GateTimeout):
            with gate.slot(timeout=0.1):
                pass
    with gate.slot(timeout=0.1):   # free again after the holder left
        pass
    assert gate.calls == 2
