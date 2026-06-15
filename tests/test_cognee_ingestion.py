"""Tests for Cognee ingestion script (doc resolution, JSON output, exit codes).

RED phase: These tests define the expected behavior for:
- ingest_cognee.py resolves docs/ directory relative to project root
- Reads all 4 reference doc files
- Uses dedicated dataset name 'kicad-agent-reference'
- ingest_doc() is a pure function returning JSON-serializable dicts
- verify_ingestion() is a pure function returning verification query dicts
- main() writes JSONL to stdout or --output file
- Proper exit codes (0 success, 1 partial failure, 2 import error)
"""

from __future__ import annotations

import json
import sys
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

import pytest

# scripts/ is not on sys.path by default; add it so we can import ingest_cognee
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from ingest_cognee import (
    DATASET_NAME,
    DOC_FILES,
    ROOT,
    VERIFICATION_QUERIES,
    ingest_doc,
    main,
    verify_ingestion,
)


class TestDocResolution:
    """Tests for docs/ directory resolution and file listing."""

    def test_root_points_to_project_dir(self) -> None:
        """ROOT should resolve to the project root (parent of scripts/)."""
        # ROOT is scripts/ parent.parent, so it should be the project root
        assert (ROOT / "scripts").is_dir()

    def test_doc_files_list_has_four_entries(self) -> None:
        """DOC_FILES should contain exactly the 4 reference document filenames."""
        assert len(DOC_FILES) == 4

    def test_doc_files_contains_expected_names(self) -> None:
        """DOC_FILES should contain the expected reference doc filenames."""
        assert "kicad_agent_reference.md" in DOC_FILES
        assert "pcb_editor_reference.md" in DOC_FILES
        assert "gerbview_reference.md" in DOC_FILES
        assert "kicad_docs.md" in DOC_FILES

    def test_dataset_name_is_dedicated(self) -> None:
        """DATASET_NAME should not be the default 'main_dataset'."""
        assert DATASET_NAME == "kicad-agent-reference"
        assert DATASET_NAME != "main_dataset"


class TestIngestDoc:
    """Tests for the ingest_doc() pure function."""

    def test_returns_dict_with_required_keys(self) -> None:
        """ingest_doc() should return a dict with tool, data, dataset_name."""
        result = ingest_doc("test.md", "some content here")
        assert isinstance(result, dict)
        assert "tool" in result
        assert "data" in result
        assert "dataset_name" in result

    def test_tool_is_remember(self) -> None:
        """ingest_doc() should use 'remember' as the tool name."""
        result = ingest_doc("test.md", "content")
        assert result["tool"] == "remember"

    def test_dataset_name_matches_constant(self) -> None:
        """ingest_doc() should use the DATASET_NAME constant."""
        result = ingest_doc("test.md", "content")
        assert result["dataset_name"] == DATASET_NAME

    def test_data_includes_source_label(self) -> None:
        """ingest_doc() should prefix content with [Source: filename]."""
        result = ingest_doc("my_doc.md", "body text")
        assert result["data"].startswith("[Source: my_doc.md]")
        assert "body text" in result["data"]

    def test_data_preserves_content(self) -> None:
        """ingest_doc() should include the full content after the label."""
        content = "Line 1\nLine 2\nLine 3"
        result = ingest_doc("test.md", content)
        assert "Line 1" in result["data"]
        assert "Line 2" in result["data"]
        assert "Line 3" in result["data"]

    def test_raises_value_error_on_empty_content(self) -> None:
        """ingest_doc() should raise ValueError if content is empty."""
        with pytest.raises(ValueError, match="empty"):
            ingest_doc("test.md", "")

    def test_raises_value_error_on_whitespace_only(self) -> None:
        """ingest_doc() should raise ValueError if content is whitespace only."""
        with pytest.raises(ValueError, match="empty"):
            ingest_doc("test.md", "   \n\n  ")

    def test_result_is_json_serializable(self) -> None:
        """ingest_doc() output should be JSON-serializable."""
        result = ingest_doc("test.md", "valid content")
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        assert parsed["tool"] == "remember"


class TestVerifyIngestion:
    """Tests for the verify_ingestion() pure function."""

    def test_returns_list(self) -> None:
        """verify_ingestion() should return a list of dicts."""
        result = verify_ingestion()
        assert isinstance(result, list)

    def test_returns_correct_number_of_queries(self) -> None:
        """verify_ingestion() should return one dict per VERIFICATION_QUERIES entry."""
        result = verify_ingestion()
        assert len(result) == len(VERIFICATION_QUERIES)

    def test_each_entry_has_required_keys(self) -> None:
        """Each verification entry should have tool, query, datasets."""
        result = verify_ingestion()
        for entry in result:
            assert "tool" in entry
            assert "query" in entry
            assert "datasets" in entry

    def test_tool_is_recall(self) -> None:
        """verify_ingestion() should use 'recall' as the tool name."""
        result = verify_ingestion()
        for entry in result:
            assert entry["tool"] == "recall"

    def test_datasets_contains_kicad_dataset(self) -> None:
        """Each verification entry should query the kicad-agent-reference dataset."""
        result = verify_ingestion()
        for entry in result:
            assert DATASET_NAME in entry["datasets"]

    def test_queries_match_verification_queries(self) -> None:
        """Verification query strings should match VERIFICATION_QUERIES."""
        result = verify_ingestion()
        queries = [entry["query"] for entry in result]
        expected_queries = [q[0] for q in VERIFICATION_QUERIES]
        assert queries == expected_queries

    def test_entries_are_json_serializable(self) -> None:
        """verify_ingestion() output should be JSON-serializable."""
        result = verify_ingestion()
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        assert len(parsed) == len(result)


class TestMainFunction:
    """Tests for the main() function dispatch."""

    def test_main_returns_zero_on_success(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        """main() should return 0 when all docs are found."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        for doc_name in DOC_FILES:
            (docs_dir / doc_name).write_text(f"Content of {doc_name}\n")

        with patch("ingest_cognee.ROOT", tmp_path):
            result = main()

        assert result == 0

    def test_main_returns_one_on_partial_failure(self, tmp_path: Path) -> None:
        """main() should return 1 when some docs are missing."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        # Only create 2 of 4 docs
        (docs_dir / DOC_FILES[0]).write_text("content\n")
        (docs_dir / DOC_FILES[1]).write_text("content\n")

        with patch("ingest_cognee.ROOT", tmp_path):
            result = main()
        assert result == 1

    def test_main_writes_jsonl_to_output_file(self, tmp_path: Path) -> None:
        """main() with --output should write JSONL to the specified file."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        for doc_name in DOC_FILES:
            (docs_dir / doc_name).write_text(f"Content of {doc_name}\n")

        output_file = tmp_path / "cmds.jsonl"
        with patch("ingest_cognee.ROOT", tmp_path):
            result = main(["--output", str(output_file)])

        assert result == 0
        assert output_file.exists()

        # Parse JSONL and verify structure
        lines = output_file.read_text().strip().split("\n")
        assert len(lines) == len(DOC_FILES) + len(VERIFICATION_QUERIES)
        for line in lines:
            obj = json.loads(line)
            assert "tool" in obj

    def test_main_prints_ingestion_and_verification_payloads(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        """main() should print 4 ingestion + N verification payloads to stdout."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        for doc_name in DOC_FILES:
            (docs_dir / doc_name).write_text(f"Content of {doc_name}\n")

        with patch("ingest_cognee.ROOT", tmp_path):
            result = main()

        assert result == 0
        stdout = capsys.readouterr().out
        lines = [l for l in stdout.strip().split("\n") if l.strip()]
        expected_count = len(DOC_FILES) + len(VERIFICATION_QUERIES)
        assert len(lines) == expected_count

        # Verify each line is valid JSON
        for line in lines:
            obj = json.loads(line)
            assert "tool" in obj

    def test_main_stderr_summary(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        """main() should print a summary to stderr."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        for doc_name in DOC_FILES:
            (docs_dir / doc_name).write_text(f"Content of {doc_name}\n")

        with patch("ingest_cognee.ROOT", tmp_path):
            main()

        stderr = capsys.readouterr().err
        assert "ingestion payloads" in stderr.lower() or "prepared" in stderr.lower()

    def test_main_returns_one_when_all_docs_missing(self, tmp_path: Path) -> None:
        """main() should return 1 when docs/ directory is empty/missing."""
        # tmp_path has no docs/ directory
        with patch("ingest_cognee.ROOT", tmp_path):
            result = main()
        assert result == 1

    def test_main_output_file_has_remember_then_recall_order(
        self, tmp_path: Path,
    ) -> None:
        """Output should have 'remember' payloads first, then 'recall' payloads."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        for doc_name in DOC_FILES:
            (docs_dir / doc_name).write_text(f"Content of {doc_name}\n")

        output_file = tmp_path / "cmds.jsonl"
        with patch("ingest_cognee.ROOT", tmp_path):
            main(["--output", str(output_file)])

        lines = output_file.read_text().strip().split("\n")
        objects = [json.loads(line) for line in lines]

        # First 4 should be 'remember' (ingestion)
        for i in range(len(DOC_FILES)):
            assert objects[i]["tool"] == "remember"

        # Remaining should be 'recall' (verification)
        for i in range(len(DOC_FILES), len(objects)):
            assert objects[i]["tool"] == "recall"
