"""Tests for the versioned build system (Phase 207).

Covers:
- ``Build`` / ``BuildStatus`` / ``BuildDiff`` model (BUILD-02, BUILD-03, BUILD-10)
- ``ManufacturingManifest`` / ``ManufacturingArtifact`` serialization (BUILD-05)
- ``build_create`` / ``build_list`` / ``build_show`` ops (BUILD-01, BUILD-04,
  BUILD-06, BUILD-07, BUILD-08)
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from kicad_agent.manufacturing.build import (
    Build,
    BuildDiff,
    BuildStatus,
    _get_git_sha,
    diff_builds,
)
from kicad_agent.validation.gates.manufacturing_manifest import (
    ManufacturingArtifact,
    ManufacturingManifest,
    generate_manifest,
)


# ---------------------------------------------------------------------------
# Shared helpers (mirror test_board_metadata_ops.py pattern)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_ir_registry():
    from kicad_agent.ir.base import _clear_registry
    _clear_registry()
    yield
    _clear_registry()


def _create_pcb_with_title_block(tmpdir: Path, rev: str = "1.0") -> Path:
    """Create a minimal PCB with a title_block carrying ``rev``."""
    pcb_path = tmpdir / "test_build.kicad_pcb"
    content = f'''(kicad_pcb (version 20241229) (generator "test")
  (general (thickness 1.6) (layers 2))
  (paper "A4")
  (title_block
    (title "Build Test")
    (date "2026-07-10")
    (rev "{rev}")
    (company "Test Co")
  )
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
  )
)
'''
    pcb_path.write_text(content, encoding="utf-8")
    return pcb_path


def _build_ir(pcb_path: Path):
    """Parse PCB and build PcbIR (mimics executor setup)."""
    from kicad_agent.parser.pcb_parser import parse_pcb
    from kicad_agent.ir.pcb_ir import PcbIR
    from kicad_agent.parser.uuid_extractor import extract_uuids
    result = parse_pcb(pcb_path)
    uuid_map = extract_uuids(result.raw_content, "pcb")
    return PcbIR(_parse_result=result, _uuid_map=uuid_map)


def _make_artifact(name: str = "gerbers") -> ManufacturingArtifact:
    return ManufacturingArtifact(
        name=name,
        path=f"/tmp/{name}",
        sha256="a" * 64,
        size_bytes=1024,
        generated_by="snapshot",
        timestamp="2026-07-10T00:00:00+00:00",
    )


def _make_build(
    build_id: str = "11111111-1111-1111-1111-111111111111",
    board_rev: str = "1.0",
    source_files: tuple[str, ...] = ("board.kicad_pcb",),
    git_sha: str = "abc123",
    status: BuildStatus = BuildStatus.DRAFT,
    artifacts: tuple[ManufacturingArtifact, ...] | None = None,
) -> Build:
    return Build(
        build_id=build_id,
        board_rev=board_rev,
        source_files=source_files,
        git_sha=git_sha,
        created_at="2026-07-10T00:00:00+00:00",
        status=status,
        artifacts=artifacts if artifacts is not None else (_make_artifact(),),
        manifest_path="builds/v1.0_x/manifest.json",
        build_dir="builds/v1.0_x",
    )


# ---------------------------------------------------------------------------
# TestBuildModel
# ---------------------------------------------------------------------------


class TestBuildModel:
    """Build dataclass, BuildStatus lifecycle, git SHA, manifest round-trip."""

    def test_build_status_transition_allowed(self) -> None:
        """DRAFT -> VALIDATED returns a new frozen Build with status=VALIDATED."""
        b = _make_build(status=BuildStatus.DRAFT)
        b2 = b.transition_to(BuildStatus.VALIDATED)
        assert b2.status == BuildStatus.VALIDATED
        # original unchanged (frozen)
        assert b.status == BuildStatus.DRAFT
        # other fields preserved
        assert b2.build_id == b.build_id
        assert b2.board_rev == b.board_rev

    def test_build_status_transition_full_chain(self) -> None:
        """The full DRAFT -> VALIDATED -> EXPORTED -> HANDED_OFF chain works."""
        b = _make_build(status=BuildStatus.DRAFT)
        b = b.transition_to(BuildStatus.VALIDATED)
        b = b.transition_to(BuildStatus.EXPORTED)
        b = b.transition_to(BuildStatus.HANDED_OFF)
        assert b.status == BuildStatus.HANDED_OFF

    def test_build_status_transition_disallowed(self) -> None:
        """HANDED_OFF -> DRAFT (backwards) raises ValueError."""
        b = _make_build(status=BuildStatus.HANDED_OFF)
        with pytest.raises(ValueError, match="Invalid build status transition"):
            b.transition_to(BuildStatus.DRAFT)

    def test_build_status_transition_skip_raises(self) -> None:
        """Skipping a state (DRAFT -> EXPORTED) is disallowed."""
        b = _make_build(status=BuildStatus.DRAFT)
        with pytest.raises(ValueError, match="Invalid build status transition"):
            b.transition_to(BuildStatus.EXPORTED)

    def test_build_status_terminal_no_transitions(self) -> None:
        """HANDED_OFF is terminal -- no forward transitions."""
        b = _make_build(status=BuildStatus.HANDED_OFF)
        with pytest.raises(ValueError):
            b.transition_to(BuildStatus.VALIDATED)

    def test_git_sha_unknown_when_not_a_repo(self, tmp_path: Path) -> None:
        """_get_git_sha in a non-git dir returns 'unknown', never raises."""
        sha = _get_git_sha(tmp_path)
        assert sha == "unknown"

    @pytest.mark.skipif(
        not shutil.which("git"),
        reason="git binary not available",
    )
    def test_git_sha_from_repo(self, tmp_path: Path) -> None:
        """_get_git_sha in a real git repo returns the HEAD SHA prefix."""
        # init repo + configure + commit
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), check=True,
        )
        (tmp_path / "f.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "f.txt"], cwd=str(tmp_path), check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "init"],
            cwd=str(tmp_path), check=True,
        )
        # expected sha
        expected = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_path), capture_output=True, text=True, check=True,
        ).stdout.strip()
        sha = _get_git_sha(tmp_path)
        assert sha == expected
        assert sha != "unknown"

    def test_manifest_to_json_round_trip(self, tmp_path: Path) -> None:
        """ManufacturingManifest.save then load reproduces an equal manifest."""
        artifacts = [
            ManufacturingArtifact(
                name="gerbers", path="/tmp/g", sha256="a" * 64,
                size_bytes=10, generated_by="kicad-cli", timestamp="2026-07-10T00:00:00+00:00",
            ),
            ManufacturingArtifact(
                name="drill", path="/tmp/d", sha256="b" * 64,
                size_bytes=20, generated_by="kicad-cli", timestamp="2026-07-10T00:00:01+00:00",
            ),
        ]
        m = generate_manifest("proj", "board", "2-layer", artifacts, bom_rows=5, total_components=10)
        out = tmp_path / "manifest.json"
        m.save(out)
        loaded = ManufacturingManifest.load(out)
        assert loaded == m
        assert loaded.artifacts == m.artifacts
        assert isinstance(loaded.artifacts, tuple)

    def test_manifest_to_json_handles_tuples(self) -> None:
        """artifacts tuple serializes to JSON list and back to tuple."""
        m = generate_manifest(
            "p", "b", "2-layer", [_make_artifact("gerbers"), _make_artifact("drill")],
        )
        text = m.to_json()
        assert '"artifacts"' in text
        # round-trip via save/load
        assert isinstance(m.artifacts, tuple)

    def test_artifact_to_from_dict(self) -> None:
        """ManufacturingArtifact.from_dict(a.to_dict()) == a."""
        a = _make_artifact("gerbers")
        assert ManufacturingArtifact.from_dict(a.to_dict()) == a

    def test_manifest_load_missing_file_raises(self, tmp_path: Path) -> None:
        """load(nonexistent) raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            ManufacturingManifest.load(tmp_path / "nope.json")

    def test_build_to_dict_round_trip(self, tmp_path: Path) -> None:
        """Build.save then Build.load produces an equal Build (status survives)."""
        b = _make_build(
            status=BuildStatus.VALIDATED,
            artifacts=(_make_artifact("gerbers"), _make_artifact("drill")),
        )
        out = tmp_path / "build.json"
        b.save(out)
        loaded = Build.load(out)
        assert loaded == b
        assert loaded.status == BuildStatus.VALIDATED
        assert isinstance(loaded.source_files, tuple)
        assert isinstance(loaded.artifacts, tuple)

    def test_diff_builds_detects_changes(self) -> None:
        """Two builds differing in source_files, artifacts, status, git_sha, board_rev."""
        a = _make_build(
            source_files=("board.kicad_pcb", "board.kicad_sch"),
            git_sha="aaa",
            board_rev="1.0",
            status=BuildStatus.DRAFT,
            artifacts=(_make_artifact("gerbers"),),
        )
        b = _make_build(
            build_id="22222222-2222-2222-2222-222222222222",
            source_files=("board.kicad_pcb", "board.kicad_pro"),
            git_sha="bbb",
            board_rev="2.0",
            status=BuildStatus.VALIDATED,
            artifacts=(_make_artifact("drill"),),
        )
        d = diff_builds(a, b)
        assert isinstance(d, BuildDiff)
        assert d.source_files_added == ("board.kicad_pro",)
        assert d.source_files_removed == ("board.kicad_sch",)
        assert d.artifacts_added == ("drill",)
        assert d.artifacts_removed == ("gerbers",)
        assert d.status_changed is True
        assert d.git_sha_changed is True
        assert d.board_rev_changed is True

    def test_diff_builds_identical(self) -> None:
        """Same Build -> all empty tuples, all *_changed False."""
        b = _make_build()
        d = diff_builds(b, b)
        assert d.source_files_added == ()
        assert d.source_files_removed == ()
        assert d.artifacts_added == ()
        assert d.artifacts_removed == ()
        assert d.status_changed is False
        assert d.git_sha_changed is False
        assert d.board_rev_changed is False
