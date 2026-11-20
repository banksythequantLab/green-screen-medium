"""Unit tests for the Flow check command (Requirement 6)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from greenscreen.flow import check

ROOT = Path(__file__).resolve().parents[2]
BUNDLED = ROOT / "greenscreen" / "flow" / "flows" / "tk5-time.yaml"


def _good(tmp_path: Path) -> Path:
    path = tmp_path / "good.yaml"
    path.write_bytes(BUNDLED.read_bytes())
    return path


def _bad_text(description: str | None = None) -> str:
    text = BUNDLED.read_text(encoding="utf-8")
    marker = "  signatures:\n  - tk5-logon\n"
    assert marker in text
    text = text.replace(marker, "  signatures:\n  - no-such-signature\n", 1)
    if description is not None:
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("description:"):
                lines[i] = "description: " + description
                break
        text = "\n".join(lines)
    return text


def _run(capsys, args):
    code = check.main(args)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_good_file_exits_zero(tmp_path, capsys):
    path = _good(tmp_path)
    code, out, err = _run(capsys, [str(path)])
    assert code == 0
    assert out == "ok: good.yaml\n"
    assert err == ""


def test_violation_exits_one_with_rule_name(tmp_path, capsys):
    path = tmp_path / "bad.yaml"
    path.write_text(_bad_text(), encoding="utf-8")
    code, out, err = _run(capsys, [str(path)])
    assert code == 1
    assert out == ""
    lines = err.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("violation:")
    assert "unknown_signature" in lines[0]
    assert "Read the current date" not in err


def test_missing_file_exits_three(tmp_path, capsys):
    code, out, err = _run(capsys, [str(tmp_path / "nope.yaml")])
    assert code == 3
    assert out == ""
    assert err == "error: file not found or not readable\n"


def test_directory_exits_three(tmp_path, capsys):
    code, out, err = _run(capsys, [str(tmp_path)])
    assert code == 3
    assert out == ""
    assert err == "error: file not found or not readable\n"


def test_unclosed_bracket_reports_position(tmp_path, capsys):
    path = tmp_path / "broken.yaml"
    path.write_text("key: [unclosed", encoding="utf-8")
    code, out, err = _run(capsys, [str(path)])
    assert code == 4
    assert out == ""
    assert err.startswith("error: not a YAML mapping (line ")
    assert ", column " in err
    assert "unclosed" not in err


def test_non_utf8_bytes_exit_four_without_position(tmp_path, capsys):
    path = tmp_path / "bin.yaml"
    path.write_bytes(b"\xff\xfe")
    code, out, err = _run(capsys, [str(path)])
    assert code == 4
    assert out == ""
    assert err == "error: not a YAML mapping\n"


def test_yaml_list_exits_four(tmp_path, capsys):
    path = tmp_path / "list.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    code, out, err = _run(capsys, [str(path)])
    assert code == 4
    assert out == ""
    assert err == "error: not a YAML mapping\n"


@pytest.mark.parametrize("args", [[], ["a", "b"], ["-x"], ["--help"], [""]])
def test_usage_errors_exit_two(args, capsys):
    code, out, err = _run(capsys, args)
    assert code == 2
    assert out == ""
    lines = err.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("usage:")


def test_signature_load_failure_exits_five(tmp_path, capsys, monkeypatch):
    import greenscreen.recognizer as recognizer

    def boom():
        raise RuntimeError("secret-cause-text")

    monkeypatch.setattr(recognizer, "load_bundled_signatures", boom)
    path = _good(tmp_path)
    code, out, err = _run(capsys, [str(path)])
    assert code == 5
    assert out == ""
    assert err == "error: bundled signatures could not be loaded\n"
    assert "secret-cause-text" not in err


def test_exit_codes_are_distinct():
    codes = [
        check.EXIT_OK,
        check.EXIT_VIOLATION,
        check.EXIT_USAGE,
        check.EXIT_NO_FILE,
        check.EXIT_NOT_YAML,
        check.EXIT_NO_SIGNATURES,
    ]
    assert all(isinstance(c, int) for c in codes)
    assert len(set(codes)) == 6


def test_file_is_not_modified(tmp_path, capsys):
    good = _good(tmp_path)
    bad = tmp_path / "bad.yaml"
    bad.write_text(_bad_text(), encoding="utf-8")
    for path in (good, bad):
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        check.main([str(path)])
        capsys.readouterr()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_description_never_appears_in_output(tmp_path, capsys):
    description = "\u00e9" + "qzxv" * 74  # 297 characters, one non-ASCII letter
    description = description + "abc"
    assert len(description) == 300
    path = tmp_path / "bad.yaml"
    path.write_text(_bad_text(description), encoding="utf-8")
    code, out, err = _run(capsys, [str(path)])
    assert code == 1
    assert "qzxv" not in out + err
    assert "\u00e9" not in out + err
    assert all(" " <= c <= "~" or c == "\n" for c in out + err)


def _clean_env() -> dict[str, str]:
    return {
        k: v for k, v in os.environ.items() if not k.startswith(("TK5_", "GS_"))
    }


def test_subprocess_good_and_missing(tmp_path):
    env = _clean_env()
    good = subprocess.run(
        [sys.executable, "-m", "greenscreen.flow.check", str(BUNDLED)],
        env=env, cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert good.returncode == 0
    assert good.stdout == "ok: tk5-time.yaml\n"
    assert good.stderr == ""
    missing = subprocess.run(
        [sys.executable, "-m", "greenscreen.flow.check", str(tmp_path / "nope.yaml")],
        env=env, cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert missing.returncode == 3
    assert missing.stdout == ""
    assert missing.stderr.strip() == "error: file not found or not readable"
