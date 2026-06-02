"""CLI subcommands package for kicad-agent.

Re-exports ``main`` and all public names from the sibling ``cli.py``
module so that ``from kicad_agent.cli import main`` works whether this
directory is present or not.
"""

import importlib.util
import os as _os
import sys as _sys

_CLI_MODULE_PATH = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "cli.py")
_spec = importlib.util.spec_from_file_location("kicad_agent._cli_impl", _CLI_MODULE_PATH)
_cli_impl = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_sys.modules["kicad_agent._cli_impl"] = _cli_impl
_spec.loader.exec_module(_cli_impl)  # type: ignore[union-attr]

# Re-export main and other public names
main = _cli_impl.main
