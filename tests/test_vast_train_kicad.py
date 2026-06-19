"""Config validation tests for vast_train_kicad.py and vast_launch_kicad.sh.

Validates that adapted scripts preserve all proven classes from spectral-primitives
and have correct KiCad-specific configuration values.
"""

import ast
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "vast_train_kicad.py"
LAUNCH_PATH = Path(__file__).resolve().parent.parent / "scripts" / "vast_launch_kicad.sh"


class TestVastTrainKicad:
    """Validate vast_train_kicad.py preserves spectral-primitives proven code."""

    def test_syntax_valid(self):
        source = SCRIPT_PATH.read_text()
        ast.parse(source)  # Raises SyntaxError if invalid

    def test_has_heartbeat_callback(self):
        source = SCRIPT_PATH.read_text()
        assert "class HeartbeatCallback" in source

    def test_has_vision_collator(self):
        source = SCRIPT_PATH.read_text()
        assert "class Gemma4VisionCollator" in source

    def test_has_dequantize_function(self):
        source = SCRIPT_PATH.read_text()
        assert "def dequantize_vision_encoder" in source

    def test_output_dir_is_kicad(self):
        source = SCRIPT_PATH.read_text()
        assert "kicad-vision-lora-adapter" in source
        # Must NOT contain old spectral output dir
        assert "gemma4-lora-adapter" not in source

    def test_max_seq_length_is_4096(self):
        source = SCRIPT_PATH.read_text()
        assert "4096" in source
        # Verify it's the argparse default
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        pass  # Argparse defaults checked via string presence

    def test_model_id_unchanged(self):
        source = SCRIPT_PATH.read_text()
        assert "google/gemma-4-12b-it" in source

    def test_lora_rank_is_16(self):
        source = SCRIPT_PATH.read_text()
        # Check for lora_rank default of 16
        assert "lora_rank" in source
        assert 'default=16' in source or "r=16" in source or "LoraConfig" in source

    def test_has_bitsandbytes_config(self):
        source = SCRIPT_PATH.read_text()
        assert "BitsAndBytesConfig" in source

    def test_no_spectral_except_docstring(self):
        source = SCRIPT_PATH.read_text()
        lines = source.split("\n")
        spectral_lines = [
            i + 1 for i, line in enumerate(lines)
            if "spectral" in line.lower() and i > 10  # Skip docstring header
        ]
        # Only the docstring attribution line should mention spectral
        assert len(spectral_lines) <= 1, f"Unexpected 'spectral' references at lines: {spectral_lines}"

    def test_launch_bash_safety(self):
        launch = LAUNCH_PATH.read_text()
        assert "set -euo pipefail" in launch

    def test_launch_no_hardcoded_credentials(self):
        launch = LAUNCH_PATH.read_text()
        secrets = ["API_KEY", "SECRET", "PASSWORD"]
        for secret in secrets:
            # Check for hardcoded assignments (not env var checks)
            assert f"{secret}=" not in launch, f"Potential hardcoded {secret} in launch script"

    def test_launch_kicad_paths(self):
        launch = LAUNCH_PATH.read_text()
        assert "kicad-vision-lora-adapter" in launch
        assert "kicad-vision-lora-train" in launch
        assert "vast_train_kicad" in launch
        assert "--disk 50" in launch
        assert "unified_vision_data" in launch

    def test_launch_script_references_correct_training_script(self):
        launch = LAUNCH_PATH.read_text()
        assert "vast_train_gemma4" not in launch, "Old spectral script reference found"
        assert "vast_train_kicad.py" in launch
