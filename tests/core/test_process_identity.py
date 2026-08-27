from unittest.mock import patch

from free_claude_code.core import process_identity


def test_build_process_title_includes_bounded_operational_detail() -> None:
    assert process_identity.build_process_title("CI pytest", "gw3") == (
        "Harness CI pytest [gw3]"
    )


def test_build_process_title_removes_control_and_shell_like_characters() -> None:
    title = process_identity.build_process_title(
        "server\nworker", "profile/one; rm -rf /"
    )

    assert title == "Harness server worker [profile-one- rm -rf]"


def test_build_process_title_is_bounded() -> None:
    title = process_identity.build_process_title("x" * 200, "y" * 200)

    assert len(title) == 80
    assert title.startswith("Harness ")


def test_set_process_identity_is_best_effort() -> None:
    with patch.object(
        process_identity.setproctitle,
        "setproctitle",
        side_effect=RuntimeError("unsupported process title"),
    ) as set_title:
        title = process_identity.set_process_identity("Server")

    assert title == "Harness Server"
    set_title.assert_called_once_with("Harness Server")
