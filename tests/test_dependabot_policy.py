"""Dependabot 自动合并策略测试。"""

from scripts.dependabot_policy import allows_auto_merge, parse_updates


def test_single_non_major_update_is_allowed() -> None:
    assert allows_auto_merge(
        "chore(deps): bump fastapi from 0.115.14 to 0.139.0",
        "",
    )


def test_single_major_update_is_rejected() -> None:
    assert not allows_auto_merge(
        "chore(deps): bump actions/upload-artifact from 4 to 7",
        "",
    )


def test_group_is_allowed_only_when_every_update_is_non_major() -> None:
    title = "chore(deps): bump the tools group with 2 updates"
    safe_body = "\n".join(
        (
            "Updates `mypy` from 2.1.0 to 2.3.0",
            "Updates `ruff` from 0.15.20 to 0.15.21",
        )
    )
    unsafe_body = safe_body.replace("2.3.0", "3.0.0")

    assert allows_auto_merge(title, safe_body)
    assert not allows_auto_merge(title, unsafe_body)


def test_group_size_mismatch_and_unknown_versions_are_rejected() -> None:
    assert not parse_updates(
        "chore(deps): bump the tools group with 2 updates",
        "Updates `ruff` from 0.15.20 to 0.15.21",
    )
    assert not allows_auto_merge("chore(deps): refresh lockfile", "")
    assert not allows_auto_merge("chore(deps): bump tool from rolling to latest", "")


def test_downgrade_is_rejected() -> None:
    assert not allows_auto_merge("chore(deps): bump tool from 2.4.0 to 2.3.0", "")
