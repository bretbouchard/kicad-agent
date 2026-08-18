"""import_symbol — symbol import into project libraries (volta-4).

Two paths: raw S-expression append, and LCSC provider → real-pinned
symbol generation via create_symbol.
"""

from __future__ import annotations

from pathlib import Path

import pytest

RAW_SYMBOL = '''  (symbol "TestLib:LM358_opamp"
    (property "Reference" "U" (at 0 0 0))
    (property "Value" "LM358" (at 0 0 0))
    (symbol "LM358_opamp_0_1"
      (rectangle (start -5.08 5.08) (end 5.08 -5.08))
    )
  )'''


def _executor(tmp_path: Path):
    from volta.ops.executor import OperationExecutor

    return OperationExecutor(base_dir=tmp_path)


class TestRawPath:
    def test_appends_to_new_library(self, tmp_path: Path):
        from volta.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "import_symbol",
                "target_file": "proj.kicad_sym",
                "symbol_sexp": RAW_SYMBOL,
            }
        })
        result = _executor(tmp_path).execute(op)
        d = result["details"]
        assert d["status"] == "ok"
        assert d["source"] == "raw"
        assert d["symbol_name"] == "TestLib:LM358_opamp"
        lib = tmp_path / "proj.kicad_sym"
        assert lib.exists()
        assert "LM358_opamp" in lib.read_text()

    def test_appends_to_existing_library(self, tmp_path: Path):
        from volta.ops.schema import Operation

        lib = tmp_path / "proj.kicad_sym"
        lib.write_text('(kicad_sym (version 20231120)\n  (symbol "Existing:R"\n  )\n)\n')
        op = Operation.model_validate({
            "root": {
                "op_type": "import_symbol",
                "target_file": "proj.kicad_sym",
                "symbol_sexp": RAW_SYMBOL,
            }
        })
        result = _executor(tmp_path).execute(op)
        assert result["details"]["status"] == "ok"
        content = lib.read_text()
        assert "Existing:R" in content and "LM358_opamp" in content

    def test_duplicate_rejected(self, tmp_path: Path):
        from volta.ops.schema import Operation

        lib = tmp_path / "proj.kicad_sym"
        lib.write_text('(kicad_sym (version 20231120)\n' + RAW_SYMBOL + "\n)\n")
        op = Operation.model_validate({
            "root": {
                "op_type": "import_symbol",
                "target_file": "proj.kicad_sym",
                "symbol_sexp": RAW_SYMBOL,
            }
        })
        result = _executor(tmp_path).execute(op)
        assert result["details"]["status"] == "error"
        assert "already exists" in result["details"]["error"]


class TestProviderPath:
    def test_pins_mapped_from_cad_data(self):
        from volta.ops.handlers.create import _pins_from_cad_data

        data = {
            "pins": [
                {"number": 1, "name": "OUT1", "x": -2.0, "y": 1.0},
                {"number": 8, "name": "V+", "x": 2.0, "y": 1.0},
            ]
        }
        pins = _pins_from_cad_data(data)
        assert [p.number for p in pins] == ["1", "8"]
        assert pins[0].name == "OUT1"
        assert pins[1].position.x > pins[0].position.x

    def test_provider_flow_monkeypatched(self, tmp_path: Path, monkeypatch):
        from volta.ops.schema import Operation
        import volta.ops.handlers.create as create_mod

        def fake_source():
            class FakeSource:
                def get_cad_data(self, part):
                    if part != "C2040":
                        return None
                    return {
                        "lcsc": "C2040",
                        "title": "LM358 Op Amp",
                        "pins": [
                            {"number": 1, "name": "OUT1", "x": -2, "y": 1},
                            {"number": 2, "name": "IN1-", "x": -2, "y": 0},
                        ],
                    }
            return FakeSource()

        monkeypatch.setattr(create_mod, "EasyEdaSource", fake_source, raising=False)
        # The handler imports EasyEdaSource inside the function from the
        # crawler module — patch at the source.
        import volta.crawler.easyeda_source as es
        monkeypatch.setattr(es, "EasyEdaSource", fake_source)

        op = Operation.model_validate({
            "root": {
                "op_type": "import_symbol",
                "target_file": "proj.kicad_sym",
                "part_number": "C2040",
                "reference_prefix": "U",
            }
        })
        result = _executor(tmp_path).execute(op)
        d = result["details"]
        assert d.get("status") == "ok", d
        assert d["source"] == "lcsc"
        assert d["pin_count"] == 2
        assert (tmp_path / "proj.kicad_sym").exists()

    def test_unknown_part_fails_actionably(self, tmp_path: Path, monkeypatch):
        from volta.ops.schema import Operation

        class FakeSource:
            def get_cad_data(self, part):
                return None

        import volta.crawler.easyeda_source as es
        monkeypatch.setattr(es, "EasyEdaSource", FakeSource)

        op = Operation.model_validate({
            "root": {
                "op_type": "import_symbol",
                "target_file": "proj.kicad_sym",
                "part_number": "C9999999",
            }
        })
        result = _executor(tmp_path).execute(op)
        d = result["details"]
        assert d["status"] == "error"
        assert "C9999999" in d["error"]


class TestSchemaValidation:
    def test_both_sources_rejected(self):
        from pydantic import ValidationError
        from volta.ops.schema import Operation

        with pytest.raises(ValidationError):
            Operation.model_validate({
                "root": {
                    "op_type": "import_symbol",
                    "target_file": "x.kicad_sym",
                    "part_number": "C1",
                    "symbol_sexp": "(symbol x)",
                }
            })

    def test_neither_source_rejected(self):
        from pydantic import ValidationError
        from volta.ops.schema import Operation

        with pytest.raises(ValidationError):
            Operation.model_validate({
                "root": {
                    "op_type": "import_symbol",
                    "target_file": "x.kicad_sym",
                }
            })
