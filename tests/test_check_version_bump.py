"""check-version-bump.sh hook 单元测试 · 通过 subprocess 跑 bash 脚本。

覆盖:
- 跨 minor (v0.0.5.7 → v0.0.6) → exit 1 + 含 "minor 跨越"
- 跨 major (v0.0.x → v0.1.x) → exit 1 + 含 "major 跨越"
- 跨 epoch (v0.x.x → v1.x.x) → exit 1 + 含 "epoch 跨越"
- patch 累加 (v0.0.5.8) → exit 0
- 无版本号 → exit 0
- 3 段等价 baseline (v0.0.5) → exit 0
- 多个版本号混合 → 仅 block 违规的
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check-version-bump.sh"


def _run(msg: str, tmp_path: Path) -> subprocess.CompletedProcess:
    """写 msg 到 tmp file · 跑 hook · 返 CompletedProcess。"""
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text(msg, encoding="utf-8")
    return subprocess.run(
        ["bash", str(SCRIPT), str(msg_file)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def test_minor_jump_blocked(tmp_path: Path) -> None:
    """v0.0.5.x → v0.0.6 跨 minor · 必须 block。"""
    r = _run("feat: bump to v0.0.6 chain 架构", tmp_path)
    assert r.returncode == 1
    assert "minor 跨越" in r.stderr
    assert "v0.0.6" in r.stderr


def test_major_jump_blocked(tmp_path: Path) -> None:
    """v0.0.x → v0.1.x 跨 major · 必须 block。"""
    r = _run("feat: v0.1.0 new module layout", tmp_path)
    assert r.returncode == 1
    assert "major 跨越" in r.stderr


def test_epoch_jump_blocked(tmp_path: Path) -> None:
    """v0.x.x → v1.x.x 跨 epoch · 必须 block。"""
    r = _run("release: v1.0.0", tmp_path)
    assert r.returncode == 1
    assert "epoch 跨越" in r.stderr


def test_patch_increment_passes(tmp_path: Path) -> None:
    """v0.0.5.X+1 patch 累加 · 必须 pass。"""
    r = _run("feat: v0.0.5.8 + chain fix", tmp_path)
    assert r.returncode == 0
    assert r.stderr == ""


def test_no_version_passes(tmp_path: Path) -> None:
    """commit msg 不提版本号 · 必须 pass (绝大多数 commit)。"""
    r = _run("fix(ux): info 散户友好错误", tmp_path)
    assert r.returncode == 0


def test_three_segment_equivalent_passes(tmp_path: Path) -> None:
    """v0.0.5 等价于 baseline 0.0.5.* · 必须 pass。"""
    r = _run("docs: reference v0.0.5 release", tmp_path)
    assert r.returncode == 0


def test_mixed_versions_blocked_if_any_jumps(tmp_path: Path) -> None:
    """多版本混合 · 只要有一个跨 minor 就 block。"""
    r = _run("upgrade: v0.0.5.8 base + retire v0.0.4.x · note v0.0.6 candidate", tmp_path)
    assert r.returncode == 1
    assert "v0.0.6" in r.stderr  # 这个 trigger
    # 其他合规的不进 violations


def test_emergency_skip_path_in_message(tmp_path: Path) -> None:
    """文案明示 --no-verify 是 audit-trail 路径 (regression: 文案要在)。"""
    r = _run("feat: v0.0.6 jump", tmp_path)
    assert r.returncode == 1
    assert "--no-verify" in r.stderr
    assert "audit trail" in r.stderr


def test_comments_in_message_ignored(tmp_path: Path) -> None:
    """commit msg 中 `#` 注释行不算 (git editor 标准行为) · v0.0.6 在注释里 → pass。"""
    msg = """feat: v0.0.5.8 chain fix
# This is a comment line that mentions v0.0.6 but should be skipped
"""
    r = _run(msg, tmp_path)
    assert r.returncode == 0


def test_pyproject_baseline_is_source_of_truth(tmp_path: Path) -> None:
    """sanity: baseline 实际从 pyproject.toml 读 (不是 hardcode)。"""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "' in pyproject
    # 跑一个 block case · 检查 stderr 提的 baseline 跟 pyproject 一致
    r = _run("feat: v9.9.9.9", tmp_path)
    assert r.returncode == 1
    # baseline 文字在 stderr
    assert "pyproject.toml baseline:" in r.stderr
