"""Fixtures shared by every app's tests.

Unit tests are local and hermetic. The tests marked `live` talk to a real
deployment — `next.tokennet.dev` by default, overridable with
TOKENNET_TEST_DOMAIN — and skip cleanly when no credential for it is
configured (TOKENNET_TEST_API_KEY, or a key stored by
`tn set-key --domain <domain>`).

App subprocesses run with HOME pointed at a temp dir, so nothing an app writes
can touch the real ~/.tokennet. The credential is passed explicitly through the
environment instead.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from apps.lib.relay import _read_var

LIVE_DOMAIN = os.environ.get("TOKENNET_TEST_DOMAIN", "next.tokennet.dev")


@pytest.fixture(scope="session")
def live_credential():
    """(domain, api_key) for the live deployment, or skip."""
    key = os.environ.get("TOKENNET_TEST_API_KEY")
    if not key:
        path = Path.home() / ".tokennet" / LIVE_DOMAIN / "credentials"
        if path.exists():
            key = _read_var(path.read_text(), "TOKENNET_API_KEY")
    if not key:
        pytest.skip(
            f"no credential for {LIVE_DOMAIN} — set TOKENNET_TEST_API_KEY, or store "
            f"one with `tn set-key --domain {LIVE_DOMAIN}` "
            "(override the target with TOKENNET_TEST_DOMAIN)"
        )
    return LIVE_DOMAIN, key


def sandboxed_env(
    tmp_path: Path, domain: str | None = None, key: str | None = None
) -> dict:
    """A subprocess environment with HOME sandboxed and, optionally, a live
    credential passed explicitly."""
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    for var in (
        "TOKENNET_DOMAIN",
        "TOKENNET_API_KEY",
        "TOKENNET_SESSION",
        "TOKENNET_RELAY_URL",
    ):
        env.pop(var, None)
    if domain:
        env["TOKENNET_DOMAIN"] = domain
    if key:
        env["TOKENNET_API_KEY"] = key
    return env


@pytest.fixture
def app_env(live_credential, tmp_path):
    domain, key = live_credential
    return sandboxed_env(tmp_path, domain, key)


def run_app(module: str, *args: str, env: dict, stdin: str | None = None):
    """Run one of the apps as a real subprocess, the way a user would."""
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        capture_output=True,
        text=True,
        env=env,
        input=stdin,
        timeout=600,
    )
