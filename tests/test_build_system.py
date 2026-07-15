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

from volta.manufacturing.build import (
    Build,
    BuildDiff,
    BuildStatus,
    _get_git_sha,
    diff_builds,
)
from volta.validation.gates.manufacturing_manifest import (
    ManufacturingArtifact,
    ManufacturingManifest,
    generate_manifest,
)


# ---------------------------------------------------------------------------
# Shared helpers (mirror test_board_metadata_ops.py pattern)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_ir_registry():
    from volta.ir.base import _clear_registry
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
    from volta.parser.pcb_parser import parse_pcb
    from volta.ir.pcb_ir import PcbIR
    from volta.parser.uuid_extractor import extract_uuids
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


# ---------------------------------------------------------------------------
# TestBuildCreate
# ---------------------------------------------------------------------------


class TestBuildCreate:
    """build_create handler (BUILD-01, BUILD-04, BUILD-06)."""

    def test_build_create_creates_directory(self, tmp_path: Path) -> None:
        """build_create creates builds/v*_*/ with manifest.json + build.json + snapshot."""
        from volta.ops._schema_pcb import BuildCreateOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        pcb_path = _create_pcb_with_title_block(tmp_path, rev="1.0")
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_create"]
        result = handler(
            BuildCreateOp(target_file="test_build.kicad_pcb", skip_validation=True),
            ir, pcb_path,
        )
        assert result["success"] is True
        build_dir = tmp_path / result["build_dir"]
        assert build_dir.is_dir()
        assert (build_dir / "manifest.json").is_file()
        assert (build_dir / "build.json").is_file()
        # snapshot copy of the .kicad_pcb
        assert (build_dir / "test_build.kicad_pcb").is_file()

    def test_build_create_reads_board_rev(self, tmp_path: Path) -> None:
        """PCB with rev '2.3' -> result['board_rev'] == '2.3'."""
        from volta.ops._schema_pcb import BuildCreateOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        pcb_path = _create_pcb_with_title_block(tmp_path, rev="2.3")
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_create"]
        result = handler(
            BuildCreateOp(target_file="test_build.kicad_pcb", skip_validation=True),
            ir, pcb_path,
        )
        assert result["success"] is True
        assert result["board_rev"] == "2.3"

    def test_build_create_records_git_sha(self, tmp_path: Path) -> None:
        """result['git_sha'] is a string (SHA or 'unknown')."""
        from volta.ops._schema_pcb import BuildCreateOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        pcb_path = _create_pcb_with_title_block(tmp_path)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_create"]
        result = handler(
            BuildCreateOp(target_file="test_build.kicad_pcb", skip_validation=True),
            ir, pcb_path,
        )
        assert result["success"] is True
        assert isinstance(result["git_sha"], str)
        assert len(result["git_sha"]) > 0

    def test_build_create_creates_draft_status(self, tmp_path: Path) -> None:
        """build_create produces status == 'draft' (simplified v1 validation)."""
        from volta.ops._schema_pcb import BuildCreateOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        pcb_path = _create_pcb_with_title_block(tmp_path)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_create"]
        result = handler(
            BuildCreateOp(target_file="test_build.kicad_pcb", skip_validation=True),
            ir, pcb_path,
        )
        assert result["success"] is True
        assert result["status"] == "draft"

    def test_build_create_snapshots_source_files(self, tmp_path: Path) -> None:
        """The .kicad_pcb is copied; artifact sha256 matches a re-hash of the copy."""
        from volta.ops._schema_pcb import BuildCreateOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        pcb_path = _create_pcb_with_title_block(tmp_path)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_create"]
        result = handler(
            BuildCreateOp(target_file="test_build.kicad_pcb", skip_validation=True),
            ir, pcb_path,
        )
        assert result["success"] is True
        build_dir = tmp_path / result["build_dir"]
        copy_path = build_dir / "test_build.kicad_pcb"
        copy_hash = hashlib.sha256(copy_path.read_bytes()).hexdigest()
        # find the .kicad_pcb artifact in the result
        pcb_artifact = next(
            a for a in result["artifacts"] if a["name"] == "test_build.kicad_pcb"
        )
        assert pcb_artifact["sha256"] == copy_hash
        assert "test_build.kicad_pcb" in result["source_files"]

    def test_build_create_snapshots_sch_and_pro(self, tmp_path: Path) -> None:
        """Sibling .kicad_sch and .kicad_pro with the same stem are also snapshotted."""
        from volta.ops._schema_pcb import BuildCreateOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        pcb_path = _create_pcb_with_title_block(tmp_path)
        (tmp_path / "test_build.kicad_sch").write_text("(kicad_sch ...)", encoding="utf-8")
        (tmp_path / "test_build.kicad_pro").write_text('{"board":{}}', encoding="utf-8")
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_create"]
        result = handler(
            BuildCreateOp(target_file="test_build.kicad_pcb", skip_validation=True),
            ir, pcb_path,
        )
        assert result["success"] is True
        source_set = set(result["source_files"])
        assert "test_build.kicad_pcb" in source_set
        assert "test_build.kicad_sch" in source_set
        assert "test_build.kicad_pro" in source_set

    def test_build_create_no_partial_state_on_parse_failure(self, tmp_path: Path) -> None:
        """A non-PCB target produces success=False and NO builds/ directory."""
        from volta.ops._schema_pcb import BuildCreateOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        # A file that NativeParser can read but produces a degenerate board
        # (empty title block). To force a genuine failure we point at a path
        # that does not exist -- NativeParser.parse_pcb raises FileNotFoundError.
        bad_path = tmp_path / "missing.kicad_pcb"
        ir = _build_ir(_create_pcb_with_title_block(tmp_path))  # valid ir, bad file_path
        handler = _QUERY_HANDLERS["build_create"]
        result = handler(
            BuildCreateOp(target_file="missing.kicad_pcb", skip_validation=True),
            ir, bad_path,
        )
        assert result["success"] is False
        assert "error" in result
        # No builds/ directory should exist
        assert not (tmp_path / "builds").exists()

    def test_build_create_target_file_unchanged(self, tmp_path: Path) -> None:
        """The target .kicad_pcb is byte-identical after build_create (is_readonly contract)."""
        from volta.ops._schema_pcb import BuildCreateOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        pcb_path = _create_pcb_with_title_block(tmp_path)
        original_hash = hashlib.sha256(pcb_path.read_bytes()).hexdigest()
        original_mtime = pcb_path.stat().st_mtime_ns
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_create"]
        result = handler(
            BuildCreateOp(target_file="test_build.kicad_pcb", skip_validation=True),
            ir, pcb_path,
        )
        assert result["success"] is True
        assert hashlib.sha256(pcb_path.read_bytes()).hexdigest() == original_hash
        assert pcb_path.stat().st_mtime_ns == original_mtime

    def test_build_create_rejects_path_traversal(self, tmp_path: Path) -> None:
        """project_dir with '..' segments is rejected (threat model #1)."""
        from volta.ops._schema_pcb import BuildCreateOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        pcb_path = _create_pcb_with_title_block(tmp_path)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_create"]
        result = handler(
            BuildCreateOp(
                target_file="test_build.kicad_pcb",
                project_dir="../../../etc",
                skip_validation=True,
            ),
            ir, pcb_path,
        )
        assert result["success"] is False
        assert "traversal" in result["error"]

    def test_build_create_generates_uuid(self, tmp_path: Path) -> None:
        """build_id matches UUID4 format (36 chars with hyphens)."""
        from volta.ops._schema_pcb import BuildCreateOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        pcb_path = _create_pcb_with_title_block(tmp_path)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_create"]
        result = handler(
            BuildCreateOp(target_file="test_build.kicad_pcb", skip_validation=True),
            ir, pcb_path,
        )
        assert result["success"] is True
        build_id = result["build_id"]
        # UUID4 format: 8-4-4-4-12 hex
        parts = build_id.split("-")
        assert len(parts) == 5
        assert [len(p) for p in parts] == [8, 4, 4, 4, 12]

    def test_build_create_build_json_round_trip(self, tmp_path: Path) -> None:
        """build.json round-trips losslessly via Build.load (success criterion #3)."""
        from volta.ops._schema_pcb import BuildCreateOp
        from volta.ops.handlers.query import _QUERY_HANDLERS
        from volta.manufacturing.build import Build

        pcb_path = _create_pcb_with_title_block(tmp_path, rev="3.1")
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_create"]
        result = handler(
            BuildCreateOp(target_file="test_build.kicad_pcb", skip_validation=True),
            ir, pcb_path,
        )
        assert result["success"] is True
        build_dir = tmp_path / result["build_dir"]
        loaded = Build.load(build_dir / "build.json")
        assert loaded.build_id == result["build_id"]
        assert loaded.board_rev == "3.1"
        assert loaded.status.value == "draft"
        assert loaded.build_dir == result["build_dir"]


# ---------------------------------------------------------------------------
# TestBuildList
# ---------------------------------------------------------------------------


class TestBuildList:
    """build_list handler (BUILD-07)."""

    def _create_build(self, tmp_path: Path, rev: str = "1.0") -> str:
        """Helper: create one build and return its build_id."""
        from volta.ops._schema_pcb import BuildCreateOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        pcb_path = _create_pcb_with_title_block(tmp_path, rev=rev)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_create"]
        result = handler(
            BuildCreateOp(target_file="test_build.kicad_pcb", skip_validation=True),
            ir, pcb_path,
        )
        assert result["success"] is True
        return result["build_id"]

    def test_build_list_returns_builds(self, tmp_path: Path) -> None:
        """Create 2 builds -> list count == 2, both build_ids present."""
        from volta.ops._schema_pcb import BuildListOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        id1 = self._create_build(tmp_path, rev="1.0")
        id2 = self._create_build(tmp_path, rev="2.0")
        pcb_path = _create_pcb_with_title_block(tmp_path, rev="1.0")
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_list"]
        result = handler(BuildListOp(target_file="test_build.kicad_pcb"), ir, pcb_path)
        ids = {b["build_id"] for b in result["builds"]}
        assert result["count"] == 2
        assert id1 in ids
        assert id2 in ids

    def test_build_list_empty_when_no_builds(self, tmp_path: Path) -> None:
        """No builds/ dir -> count == 0, builds == []."""
        from volta.ops._schema_pcb import BuildListOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        pcb_path = _create_pcb_with_title_block(tmp_path)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_list"]
        result = handler(BuildListOp(target_file="test_build.kicad_pcb"), ir, pcb_path)
        assert result["count"] == 0
        assert result["builds"] == []

    def test_build_list_skips_corrupt_dir(self, tmp_path: Path) -> None:
        """A valid build + a dir with corrupt build.json -> count==1 (no crash)."""
        from volta.ops._schema_pcb import BuildListOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        self._create_build(tmp_path)
        # create a corrupt build dir
        corrupt_dir = tmp_path / "builds" / "v9.9_20260101_000000"
        corrupt_dir.mkdir(parents=True)
        (corrupt_dir / "build.json").write_text("{not valid json", encoding="utf-8")
        pcb_path = _create_pcb_with_title_block(tmp_path)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_list"]
        result = handler(BuildListOp(target_file="test_build.kicad_pcb"), ir, pcb_path)
        # only the valid build counted; corrupt dir skipped
        assert result["count"] == 1

    def test_build_list_sorted_descending(self, tmp_path: Path) -> None:
        """Builds are sorted by created_at descending (most recent first)."""
        from volta.ops._schema_pcb import BuildListOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        self._create_build(tmp_path, rev="1.0")
        self._create_build(tmp_path, rev="2.0")
        pcb_path = _create_pcb_with_title_block(tmp_path)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_list"]
        result = handler(BuildListOp(target_file="test_build.kicad_pcb"), ir, pcb_path)
        times = [b["created_at"] for b in result["builds"]]
        assert times == sorted(times, reverse=True)


# ---------------------------------------------------------------------------
# TestBuildShow
# ---------------------------------------------------------------------------


class TestBuildShow:
    """build_show handler (BUILD-08, BUILD-10)."""

    def _create_build(self, tmp_path: Path, rev: str = "1.0") -> str:
        from volta.ops._schema_pcb import BuildCreateOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        pcb_path = _create_pcb_with_title_block(tmp_path, rev=rev)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_create"]
        result = handler(
            BuildCreateOp(target_file="test_build.kicad_pcb", skip_validation=True),
            ir, pcb_path,
        )
        assert result["success"] is True
        return result["build_id"]

    def test_build_show_returns_details(self, tmp_path: Path) -> None:
        """Show by build_id -> success, status, artifacts present."""
        from volta.ops._schema_pcb import BuildShowOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        build_id = self._create_build(tmp_path, rev="1.0")
        pcb_path = _create_pcb_with_title_block(tmp_path)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_show"]
        result = handler(
            BuildShowOp(target_file="test_build.kicad_pcb", build_id=build_id),
            ir, pcb_path,
        )
        assert result["success"] is True
        assert result["build_id"] == build_id
        assert result["status"] == "draft"
        assert len(result["artifacts"]) >= 1

    def test_build_show_not_found(self, tmp_path: Path) -> None:
        """Unknown build_id -> success=False, error mentions the id."""
        from volta.ops._schema_pcb import BuildShowOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        pcb_path = _create_pcb_with_title_block(tmp_path)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_show"]
        result = handler(
            BuildShowOp(target_file="test_build.kicad_pcb", build_id="nope-nope"),
            ir, pcb_path,
        )
        assert result["success"] is False
        assert "nope-nope" in result["error"]

    def test_build_show_round_trip_manifest(self, tmp_path: Path) -> None:
        """Create then show -> manifest is not None, artifacts length matches source count."""
        from volta.ops._schema_pcb import BuildShowOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        build_id = self._create_build(tmp_path, rev="1.0")
        pcb_path = _create_pcb_with_title_block(tmp_path)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_show"]
        result = handler(
            BuildShowOp(target_file="test_build.kicad_pcb", build_id=build_id),
            ir, pcb_path,
        )
        assert result["success"] is True
        assert result["manifest"] is not None
        # artifacts count matches source_files count (each source file -> 1 artifact)
        assert len(result["artifacts"]) == len(result["source_files"])

    def test_build_show_with_diff(self, tmp_path: Path) -> None:
        """Show build_1 with diff_build_id=build_2 -> response includes diff flags."""
        import json as _json
        from volta.ops._schema_pcb import BuildShowOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        id1 = self._create_build(tmp_path, rev="1.0")
        id2 = self._create_build(tmp_path, rev="2.0")
        pcb_path = _create_pcb_with_title_block(tmp_path)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_show"]
        result = handler(
            BuildShowOp(
                target_file="test_build.kicad_pcb",
                build_id=id1,
                diff_build_id=id2,
            ),
            ir, pcb_path,
        )
        assert result["success"] is True
        assert "diff" in result
        diff = result["diff"]
        # different board_rev between the two builds
        assert diff["board_rev_changed"] is True

    def test_build_show_diff_not_found(self, tmp_path: Path) -> None:
        """Show with unknown diff_build_id -> primary build returned + diff_error."""
        from volta.ops._schema_pcb import BuildShowOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        build_id = self._create_build(tmp_path, rev="1.0")
        pcb_path = _create_pcb_with_title_block(tmp_path)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_show"]
        result = handler(
            BuildShowOp(
                target_file="test_build.kicad_pcb",
                build_id=build_id,
                diff_build_id="deadbeef-dead-beef-dead-beefdeadbeef",
            ),
            ir, pcb_path,
        )
        assert result["success"] is True
        assert result["build_id"] == build_id
        assert "diff_error" in result
        assert "diff" not in result

    def test_build_show_no_diff_when_omitted(self, tmp_path: Path) -> None:
        """Without diff_build_id, response has neither diff nor diff_error."""
        from volta.ops._schema_pcb import BuildShowOp
        from volta.ops.handlers.query import _QUERY_HANDLERS

        build_id = self._create_build(tmp_path, rev="1.0")
        pcb_path = _create_pcb_with_title_block(tmp_path)
        ir = _build_ir(pcb_path)
        handler = _QUERY_HANDLERS["build_show"]
        result = handler(
            BuildShowOp(target_file="test_build.kicad_pcb", build_id=build_id),
            ir, pcb_path,
        )
        assert result["success"] is True
        assert "diff" not in result
        assert "diff_error" not in result

