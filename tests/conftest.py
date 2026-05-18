"""Shared test fixtures for kicad-agent parser tests.

Provides paths to real KiCad 10 template files installed at:
    /Applications/KiCad/KiCad.app/Contents/SharedSupport/template/

These fixtures use KiCad's built-in Arduino_Mega template project for testing
all four file types (.kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod).
"""

from pathlib import Path
import shutil

import pytest

# Test fixture directory for copied KiCad files
FIXTURE_DIR = Path(__file__).parent / "fixtures"

# KiCad application templates directory (KiCad 10 on macOS)
KICAD_TEMPLATES = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/template")


@pytest.fixture
def arduino_mega_sch() -> Path:
    """Path to Arduino_Mega.kicad_sch from KiCad templates.

    Returns:
        Path to a real KiCad schematic with components, wires, and labels.
    """
    return KICAD_TEMPLATES / "Arduino_Mega" / "Arduino_Mega.kicad_sch"


@pytest.fixture
def arduino_mega_pcb() -> Path:
    """Path to Arduino_Mega.kicad_pcb from KiCad templates.

    Returns:
        Path to a real KiCad PCB with footprints, nets, and traces.
    """
    return KICAD_TEMPLATES / "Arduino_Mega" / "Arduino_Mega.kicad_pcb"


@pytest.fixture
def arduino_mounting_hole_mod() -> Path:
    """Path to MountingHole_3.2mm.kicad_mod from KiCad templates.

    Returns:
        Path to a real KiCad footprint with pads and graphics.
    """
    return (
        KICAD_TEMPLATES
        / "Arduino_Mega"
        / "Arduino_MountingHole.pretty"
        / "MountingHole_3.2mm.kicad_mod"
    )


@pytest.fixture
def sample_sym_lib() -> Path:
    """Path to Device.kicad_sym symbol library.

    Uses the Device library from KiCad's shared symbols directory.
    Contains hundreds of symbols for comprehensive testing.

    Returns:
        Path to a real KiCad symbol library file.
    """
    return Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/Device.kicad_sym")


@pytest.fixture
def tmp_output_dir(tmp_path: Path) -> Path:
    """Temporary directory for test output files.

    Uses pytest's built-in tmp_path fixture for automatic cleanup.

    Returns:
        Path to a clean temporary directory.
    """
    return tmp_path


def copy_to_fixtures(src: Path, name: str) -> Path:
    """Copy a KiCad file into the fixtures directory for isolated testing.

    Args:
        src: Source file path to copy.
        name: Target filename in the fixtures directory.

    Returns:
        Path to the copied file in the fixtures directory.
    """
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    dest = FIXTURE_DIR / name
    shutil.copy2(src, dest)
    return dest
