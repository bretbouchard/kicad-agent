"""High-level fetch orchestrator for ADI footprint library.

Wires together cache, client, validation, and library registration
into a single fetch pipeline.

Fetch flow:
1. Check cache -> return cached result if hit
2. Search SamacSys -> if found, download ZIP
3. Extract ZIP -> validate with kiutils
4. Store in cache
5. Register in sym-lib-table and fp-lib-table

Falls back to manual ZIP import if automated download fails.

Security:
- T-12-08: kiutils Footprint.parse() validates downloaded .kicad_mod structure
- T-12-09: Content validation (kicad_symbol_lib check) for .kicad_sym files
- T-12-10: LibTable.add() validates names via _SAFE_ID_PATTERN
- T-12-11: LibTable MAX_ENTRIES=1000 prevents unbounded lib table growth
"""

import logging
import re
from pathlib import Path
from typing import Optional

from kicad_agent.project.adi_library.cache import FootprintCache
from kicad_agent.project.adi_library.client import SamacSysClient
from kicad_agent.project.adi_library.types import FetchResult
from kicad_agent.project.lib_table import (
    LibEntry,
    LibTable,
    parse_lib_table,
    serialize_lib_table,
)

logger = logging.getLogger(__name__)

# Default library names for ADI parts
DEFAULT_FP_LIB_NAME = "ADI_Local"
DEFAULT_SYM_LIB_NAME = "ADI_Local"

# Part number validation: alphanumeric start, then alphanumeric/dash/dot/underscore/slash
_PART_NUMBER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-._/]*$")


class AdiFetcher:
    """Orchestrates footprint/symbol fetching from SamacSys with caching.

    Usage:
        fetcher = AdiFetcher(project_dir=Path("/path/to/kicad_project"))
        result = fetcher.fetch_part("AD8606ARMZ")
        if result.footprint_path:
            print(f"Footprint: {result.footprint_path}")

        # Manual import:
        result = fetcher.import_zip(Path("AD8606ARMZ.zip"), "AD8606ARMZ")
    """

    def __init__(
        self,
        project_dir: Path,
        cache_dir_name: str = ".adi_cache",
        fp_lib_name: str = DEFAULT_FP_LIB_NAME,
        sym_lib_name: str = DEFAULT_SYM_LIB_NAME,
    ) -> None:
        """Initialize fetcher with project directory.

        Args:
            project_dir: Path to the KiCad project directory
                (where .kicad_pro lives).
            cache_dir_name: Name of the cache subdirectory within project_dir.
            fp_lib_name: Library name for footprint registration in fp-lib-table.
            sym_lib_name: Library name for symbol registration in sym-lib-table.
        """
        self._project_dir = project_dir
        self._fp_lib_name = fp_lib_name
        self._sym_lib_name = sym_lib_name
        self._cache = FootprintCache(project_dir / cache_dir_name)
        self._client = SamacSysClient()

    def close(self) -> None:
        """Close underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "AdiFetcher":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def fetch_part(self, part_number: str) -> FetchResult:
        """Fetch footprint and symbol for a given part number.

        Pipeline:
        1. Validate part number
        2. Check cache -> return cached result
        3. Search SamacSys
        4. Download ZIP if available
        5. Extract, validate, cache, register
        6. Return result

        If automated fetch fails, returns FetchResult with None paths
        and the user should use import_zip() as fallback.

        Args:
            part_number: Part number to fetch (e.g. 'AD8606ARMZ').

        Returns:
            FetchResult with paths to cached files or error indication.

        Raises:
            ValueError: If the part number format is invalid.
        """
        if not _PART_NUMBER_PATTERN.match(part_number):
            raise ValueError(f"Invalid part number: {part_number!r}")

        # Step 1: Check cache
        if self._cache.is_cached(part_number):
            paths = self._cache.get_cached_paths(part_number)
            logger.info("Cache hit for %s", part_number)
            return FetchResult(
                part_number=part_number,
                footprint_path=paths["footprint"],
                symbol_path=paths["symbol"],
                model_3d_path=None,
                source="cache",
                from_cache=True,
            )

        # Step 2: Search SamacSys
        search_result = self._client.search_part(part_number)

        if search_result.error or not search_result.has_kicad:
            logger.warning(
                "SamacSys search failed for %s: %s",
                part_number,
                search_result.error or "No KiCad download available",
            )
            return FetchResult(
                part_number=part_number,
                footprint_path=None,
                symbol_path=None,
                model_3d_path=None,
                source="samacsys",
                from_cache=False,
            )

        # Step 3: Download ZIP
        if not search_result.download_url:
            return FetchResult(
                part_number=part_number,
                footprint_path=None,
                symbol_path=None,
                model_3d_path=None,
                source="samacsys",
                from_cache=False,
            )

        temp_dir = self._cache.cache_root / "_temp"
        temp_dir.mkdir(exist_ok=True)

        zip_path = self._client.download_library(
            search_result.download_url,
            temp_dir,
        )

        if zip_path is None:
            logger.warning("Download failed for %s", part_number)
            return FetchResult(
                part_number=part_number,
                footprint_path=None,
                symbol_path=None,
                model_3d_path=None,
                source="samacsys",
                from_cache=False,
            )

        # Step 4: Extract, validate, register
        return self._process_downloaded_zip(zip_path, part_number, "samacsys")

    def import_zip(self, zip_path: Path, part_number: str) -> FetchResult:
        """Import a user-provided ZIP file into the cache.

        This is the manual fallback when automated SamacSys download fails.
        Validates the part number, extracts the ZIP, validates KiCad files,
        stores in cache, and registers in lib tables.

        Args:
            zip_path: Path to the ZIP file containing .kicad_mod/.kicad_sym.
            part_number: Part number to associate with the files.

        Returns:
            FetchResult with paths to cached files.

        Raises:
            ValueError: If part_number is invalid.
            FileNotFoundError: If zip_path does not exist.
        """
        if not _PART_NUMBER_PATTERN.match(part_number):
            raise ValueError(f"Invalid part number: {part_number!r}")
        if not zip_path.exists():
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")

        return self._process_downloaded_zip(zip_path, part_number, "manual")

    def import_files(
        self,
        part_number: str,
        footprint_path: Optional[Path] = None,
        symbol_path: Optional[Path] = None,
    ) -> FetchResult:
        """Import individual .kicad_mod and .kicad_sym files.

        Alternative to import_zip when files are already extracted.

        Args:
            part_number: Part number to associate.
            footprint_path: Path to .kicad_mod file, or None.
            symbol_path: Path to .kicad_sym file, or None.

        Returns:
            FetchResult with cached paths.

        Raises:
            ValueError: If part_number is invalid.
        """
        if not _PART_NUMBER_PATTERN.match(part_number):
            raise ValueError(f"Invalid part number: {part_number!r}")

        # Validate files before caching
        if footprint_path and footprint_path.exists():
            self._validate_footprint(footprint_path)
        if symbol_path and symbol_path.exists():
            self._validate_symbol(symbol_path)

        self._cache.add_entry(
            part_number,
            source="local",
            footprint_path=footprint_path,
            symbol_path=symbol_path,
        )

        paths = self._cache.get_cached_paths(part_number)

        # Register in lib tables
        if paths.get("footprint"):
            self._register_footprint_library()
        if paths.get("symbol"):
            self._register_symbol_library()

        return FetchResult(
            part_number=part_number,
            footprint_path=paths.get("footprint"),
            symbol_path=paths.get("symbol"),
            model_3d_path=None,
            source="local",
            from_cache=False,
        )

    def _process_downloaded_zip(
        self, zip_path: Path, part_number: str, source: str
    ) -> FetchResult:
        """Extract ZIP, validate files, cache, and register.

        Returns FetchResult with paths to cached files.
        """
        # Extract with cache (handles validation and registration)
        result = self._cache.extract_zip_safe(zip_path, part_number, source)

        # Validate extracted files with kiutils
        if result.footprint_path and result.footprint_path.exists():
            try:
                self._validate_footprint(result.footprint_path)
            except Exception as e:
                logger.warning(
                    "Footprint validation failed for %s: %s", part_number, e
                )
                result = FetchResult(
                    part_number=part_number,
                    footprint_path=None,
                    symbol_path=result.symbol_path,
                    model_3d_path=result.model_3d_path,
                    source=source,
                    from_cache=False,
                )

        if result.symbol_path and result.symbol_path.exists():
            try:
                self._validate_symbol(result.symbol_path)
            except Exception as e:
                logger.warning(
                    "Symbol validation failed for %s: %s", part_number, e
                )
                result = FetchResult(
                    part_number=part_number,
                    footprint_path=result.footprint_path,
                    symbol_path=None,
                    model_3d_path=result.model_3d_path,
                    source=source,
                    from_cache=False,
                )

        # Register in lib tables if we have valid files
        if result.footprint_path:
            self._register_footprint_library()
        if result.symbol_path:
            self._register_symbol_library()

        return result

    def _validate_footprint(self, footprint_path: Path) -> None:
        """Validate a .kicad_mod file using kiutils (T-12-08).

        Args:
            footprint_path: Path to the .kicad_mod file to validate.

        Raises:
            Exception: If the file cannot be parsed as a valid KiCad footprint.
        """
        from kiutils.footprint import Footprint

        Footprint.from_file(str(footprint_path))

    def _validate_symbol(self, symbol_path: Path) -> None:
        """Validate a .kicad_sym file using content check (T-12-09).

        Checks that the file contains the kicad_symbol_lib S-expression
        header, which is required for a valid KiCad symbol library.

        Args:
            symbol_path: Path to the .kicad_sym file to validate.

        Raises:
            ValueError: If the file is not a valid KiCad symbol library.
        """
        content = symbol_path.read_text(encoding="utf-8")
        if "(kicad_symbol_lib" not in content:
            raise ValueError(
                f"File does not appear to be a valid KiCad symbol library: "
                f"{symbol_path}"
            )

    def _register_footprint_library(self) -> None:
        """Register the ADI footprint library in fp-lib-table (T-12-10, T-12-11)."""
        fp_table_path = self._project_dir / "fp-lib-table"

        try:
            table = parse_lib_table(fp_table_path)
        except (FileNotFoundError, ValueError):
            table = LibTable(table_type="fp_lib_table")

        # Check if already registered
        try:
            table.get(self._fp_lib_name)
            return  # Already registered
        except KeyError:
            pass

        entry = LibEntry(
            name=self._fp_lib_name,
            type="KiCad",
            uri="${KIPRJMOD}/.adi_cache/footprints",
            descr="ADI parts fetched by kicad-agent",
        )
        table.add(entry)
        serialize_lib_table(table, fp_table_path)
        logger.info("Registered %s in fp-lib-table", self._fp_lib_name)

    def _register_symbol_library(self) -> None:
        """Register the ADI symbol library in sym-lib-table (T-12-10, T-12-11)."""
        sym_table_path = self._project_dir / "sym-lib-table"

        try:
            table = parse_lib_table(sym_table_path)
        except (FileNotFoundError, ValueError):
            table = LibTable(table_type="sym_lib_table")

        # Check if already registered
        try:
            table.get(self._sym_lib_name)
            return  # Already registered
        except KeyError:
            pass

        entry = LibEntry(
            name=self._sym_lib_name,
            type="KiCad",
            uri="${KIPRJMOD}/.adi_cache/symbols",
            descr="ADI parts fetched by kicad-agent",
        )
        table.add(entry)
        serialize_lib_table(table, sym_table_path)
        logger.info("Registered %s in sym-lib-table", self._sym_lib_name)
