"""The jury driven as a real subprocess — the paths that need no deployment:
`--list`, and the failures that must happen before a single token is spent."""

from apps.conftest import run_app, sandboxed_env

MODULE = "apps.jury.jury"


def test_jury_list_prints_the_roster_without_a_network(tmp_path):
    result = run_app(MODULE, "--list", env=sandboxed_env(tmp_path))
    assert result.returncode == 0, result.stderr
    assert "13 personas" in result.stdout
    assert "The Evidence Skeptic" in result.stdout
    assert "The Marketing Cynic" in result.stdout


def test_jury_a_bad_panel_fails_before_the_network(tmp_path):
    # The seating check runs before any document fetch or token is spent.
    doc = tmp_path / "doc.txt"
    doc.write_text("A claim.")
    result = run_app(MODULE, str(doc), "--panel", "99", env=sandboxed_env(tmp_path))
    assert result.returncode != 0
    assert "no persona numbered 99" in result.stderr


def test_jury_without_a_credential_fails_cleanly(tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text("A claim.")
    result = run_app(MODULE, str(doc), env=sandboxed_env(tmp_path))
    assert result.returncode != 0
    assert "credential" in result.stderr.lower()
