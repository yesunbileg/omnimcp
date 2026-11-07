"""CI gates desktop effects and distinguishes a known compositor teardown failure."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/hyprland-vm/ci_result.py"
EVIDENCE = Path(__file__).resolve().parents[1] / "docs/evidence/audit-fixes-vm-2026-11-07"


@pytest.fixture
def results(tmp_path):
    report = json.loads((EVIDENCE / "desktop-acceptance.json").read_text())
    (tmp_path / "desktop-acceptance.json").write_text(json.dumps(report))
    shutil.copyfile(EVIDENCE / "desktop-acceptance.png", tmp_path / "desktop-acceptance.png")
    marker = report["checks"]["keyboard"]
    (tmp_path / Path(marker["marker"]).name).write_text(marker["value"] + "\n")
    (tmp_path / "compositor-exit.json").write_text('{"exit_code":0}')
    (tmp_path / "serial.log").write_text("GUEST_RESULT=0\n")
    return tmp_path


def evaluate(results, code):
    spec = importlib.util.spec_from_file_location("vm_ci_result", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.evaluate(results, code)


def test_clean_desktop_and_teardown_pass(results):
    outcome = evaluate(results, 0)
    assert outcome["desktop"] == "passed"
    assert outcome["teardown"] == "passed"
    assert outcome["release_ready"] is True


def test_known_teardown_preserved_as_non_green_release_gate(results):
    (results / "compositor-exit.json").write_text('{"exit_code":139}')
    (results / "serial.log").write_text(
        "Hyprland[238]: segfault at 10 in libaquamarine.so.0.10.0\nGUEST_RESULT=0\n"
    )
    outcome = evaluate(results, 2)
    assert outcome["desktop"] == "passed"
    assert outcome["teardown"] == "known_failure"
    assert outcome["raw_exit_code"] == 2
    assert outcome["release_ready"] is False


@pytest.mark.parametrize("raw_exit", [1, 124, 137])
def test_known_signature_does_not_hide_runner_or_timeout_failure(results, raw_exit):
    (results / "compositor-exit.json").write_text('{"exit_code":139}')
    (results / "serial.log").write_text("Hyprland: segfault in libaquamarine.so.0.10.0\n")
    with pytest.raises(ValueError):
        evaluate(results, raw_exit)


def test_unknown_compositor_crash_fails_desktop_ci(results):
    (results / "compositor-exit.json").write_text('{"exit_code":139}')
    (results / "serial.log").write_text("Hyprland: segfault in another-library.so\n")
    with pytest.raises(ValueError):
        evaluate(results, 2)


@pytest.mark.parametrize("artifact", ["desktop-acceptance.png", "compositor-exit.json"])
def test_missing_evidence_fails_ci(results, artifact):
    (results / artifact).unlink()
    with pytest.raises(ValueError):
        evaluate(results, 0)


def test_acceptance_failure_is_not_hidden_by_known_teardown(results):
    path = results / "desktop-acceptance.json"
    report = json.loads(path.read_text())
    report["checks"]["keyboard"]["status"] = "failed"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        evaluate(results, 0)


def test_missing_keyboard_effect_fails_ci(results):
    path = results / "desktop-acceptance.json"
    report = json.loads(path.read_text())
    (results / Path(report["checks"]["keyboard"]["marker"]).name).unlink()
    with pytest.raises(ValueError):
        evaluate(results, 0)
