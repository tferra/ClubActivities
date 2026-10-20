import pytest

from garmin_hub.accounts import deletion


@pytest.fixture
def isolated_registry(monkeypatch):
    monkeypatch.setattr(deletion, "_STEPS", {})


def test_order_and_duplicates(isolated_registry) -> None:
    calls = []
    deletion.register_deletion_step("b", 20, lambda ctx, uid: calls.append("b"))
    deletion.register_deletion_step("a", 10, lambda ctx, uid: calls.append("a"))
    with pytest.raises(ValueError):
        deletion.register_deletion_step("a", 30, lambda ctx, uid: None)
    assert deletion.run_steps(object(), "uid") == ["a", "b"]
    assert calls == ["a", "b"]


def test_reports_first_failure(isolated_registry) -> None:
    calls = []

    def boom(ctx, uid):
        raise RuntimeError("x")

    deletion.register_deletion_step("ok", 1, lambda ctx, uid: calls.append("ok"))
    deletion.register_deletion_step("boom", 2, boom)
    deletion.register_deletion_step("never", 3, lambda ctx, uid: calls.append("never"))
    with pytest.raises(deletion.StepFailed) as exc:
        deletion.run_steps(object(), "uid")
    assert exc.value.step == "boom"
    assert calls == ["ok"]


def test_builtin_steps_registered() -> None:
    names = [s.name for s in deletion.registered_steps()]
    assert names == ["delete_reset_codes", "null_invitation_refs"]
