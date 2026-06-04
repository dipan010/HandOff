"""Tests for app.pause_gate — per-session pause/resume coordination."""

import asyncio
import threading

import pytest

from app import pause_gate


@pytest.fixture(autouse=True)
def reset_gates():
    with pause_gate._gates_lock:
        pause_gate._gates.clear()
    yield
    with pause_gate._gates_lock:
        pause_gate._gates.clear()


class TestPauseGate:
    def test_dataclass_defaults(self):
        gate = pause_gate.PauseGate()
        assert gate.approved is False
        assert gate.user_input is None
        assert gate.reason == ""
        assert isinstance(gate.event, asyncio.Event)
        assert not gate.event.is_set()


class TestGetOrCreate:
    def test_creates_new_gate(self):
        g = pause_gate.get_or_create("sess1")
        assert isinstance(g, pause_gate.PauseGate)

    def test_returns_same_instance_for_same_session(self):
        g1 = pause_gate.get_or_create("sess1")
        g2 = pause_gate.get_or_create("sess1")
        assert g1 is g2

    def test_different_sessions_get_different_gates(self):
        g1 = pause_gate.get_or_create("a")
        g2 = pause_gate.get_or_create("b")
        assert g1 is not g2

    def test_threadsafe_concurrent_creation(self):
        """Multiple threads creating gates for the same session must converge to one."""
        gates_seen: list[pause_gate.PauseGate] = []
        lock = threading.Lock()

        def worker():
            g = pause_gate.get_or_create("shared")
            with lock:
                gates_seen.append(g)

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(gates_seen) == 50
        # All threads must have received the SAME gate instance
        assert all(g is gates_seen[0] for g in gates_seen)


class TestRelease:
    def test_removes_gate(self):
        pause_gate.get_or_create("sess1")
        pause_gate.release("sess1")
        # Next get_or_create returns a fresh gate, not the old one
        assert "sess1" not in pause_gate._gates

    def test_release_unknown_session_is_noop(self):
        pause_gate.release("never-existed")  # must not raise

    def test_release_then_recreate(self):
        g1 = pause_gate.get_or_create("s")
        pause_gate.release("s")
        g2 = pause_gate.get_or_create("s")
        assert g1 is not g2


class TestEventBehaviour:
    async def test_wait_then_set(self):
        gate = pause_gate.get_or_create("s")
        gate.approved = False
        gate.user_input = None

        async def setter():
            await asyncio.sleep(0.01)
            gate.approved = True
            gate.user_input = "typed-input"
            gate.event.set()

        await asyncio.gather(setter(), gate.event.wait())
        assert gate.approved is True
        assert gate.user_input == "typed-input"
