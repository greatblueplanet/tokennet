"""The jury against a real deployment. Skipped without a credential."""

import pytest

from apps.conftest import run_app
from apps.lib.relay import Relay

pytestmark = pytest.mark.live

DOCUMENT = """\
Acme Turbo makes your team twice as fast.

In a survey, nine of our users said they felt more productive after adopting it.
Acme Turbo is proven to double productivity.
"""


def test_jury_end_to_end(app_env, tmp_path):
    """The whole app against the real network: claims extracted, a two-persona
    panel deliberating, the tally and report rendered locally."""
    relay = Relay(
        f"https://data.{app_env['TOKENNET_DOMAIN']}", app_env["TOKENNET_API_KEY"]
    )
    if relay.fleet_width("any") == 0:
        pytest.skip("no maker is online on the target deployment right now")

    doc = tmp_path / "press-release.txt"
    doc.write_text(DOCUMENT)
    out = tmp_path / "verdict.md"
    result = run_app(
        "apps.jury.jury",
        str(doc),
        "--panel",
        "2,4",
        "--output",
        str(out),
        env=app_env,
    )
    assert result.returncode == 0, result.stderr

    assert "Empanelled jury (2 of 13)" in result.stderr
    report = out.read_text()
    assert "# Second opinion" in report
    assert "The Evidence Skeptic" in report and "The Charitable Reader" in report
    # Whatever the jurors decided, every vote must carry a maker byline —
    # " via <maker>" — because an unauditable verdict is just another opinion.
    assert " via " in report, f"no maker bylines in:\n{report}"
