import base64
import json
from pathlib import Path

from free_claude_code.application.account_identity import fcc_provider_account_summary


def _jwt(**claims: object) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def _write_credentials(path: Path, *, email: str) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "credentials": {
                    "id_token": _jwt(email=email),
                    "access_token": "access-secret",
                    "refresh_token": "refresh-secret",
                },
            }
        ),
        encoding="utf-8",
    )


def test_fcc_provider_summary_reads_identity_without_returning_credentials(
    tmp_path: Path,
):
    path = tmp_path / "openai.json"
    _write_credentials(path, email="fcc@example.com")

    assert fcc_provider_account_summary(path) == "fcc@example.com"


def test_fcc_provider_summary_reads_the_openai_profile_claim(tmp_path: Path):
    path = tmp_path / "openai.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "credentials": {
                    "id_token": _jwt(
                        **{
                            "https://api.openai.com/profile": {
                                "email": "profile@example.com"
                            }
                        }
                    )
                },
            }
        ),
        encoding="utf-8",
    )

    assert fcc_provider_account_summary(path) == "profile@example.com"


def test_fcc_provider_summary_distinguishes_missing_and_invalid_files(tmp_path: Path):
    path = tmp_path / "openai.json"

    assert fcc_provider_account_summary(path) == "not connected"
    path.write_text("not-json", encoding="utf-8")
    assert fcc_provider_account_summary(path) == "needs attention"
