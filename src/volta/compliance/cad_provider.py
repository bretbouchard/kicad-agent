"""CAD model provider protocol for importing CAD models from external sources.

This module defines the CADModelProvider protocol that enables different
CAD model import engines to be plugged into the component system.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Set, Optional, List
from enum import Enum
import tempfile

from volta.governance import GovernedExecutionContext, run_governed_import


class CADModelCapability(str, Enum):
    """Capabilities that a CAD model provider can offer."""
    FOOTPRINTS = "footprints"
    SYMBOLS = "symbols" 
    MODELS_3D = "3dModels"
    DATASHEETS = "datasheets"
    SPECIFICATIONS = "specifications"


@dataclass(frozen=True)
class CADModelImportResult:
    """Result from importing CAD models."""
    
    success: bool
    """Whether the import succeeded."""
    
    imported_components: List[dict]
    """List of components that were successfully imported."""
    
    errors: List[str]
    """List of errors encountered during import."""
    
    warnings: List[str]
    """List of warnings encountered during import."""
    
    metadata: dict
    """Additional metadata about the import."""
    
    def __post_init__(self):
        if self.imported_components is None:
            object.__setattr__(self, 'imported_components', [])
        if self.errors is None:
            object.__setattr__(self, 'errors', [])
        if self.warnings is None:
            object.__setattr__(self, 'warnings', [])
        if self.metadata is None:
            object.__setattr__(self, 'metadata', {})


class CADModelProvider(ABC):
    """Protocol defining the interface for CAD model providers.
    
    This protocol allows different CAD model import systems to be used
    interchangeably. All providers must implement these methods to be
    compatible with the CAD model import system.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Get the name of this CAD model provider."""
        ...
        
    @property
    @abstractmethod
    def capabilities(self) -> Set[CADModelCapability]:
        """Get the set of capabilities this provider offers."""
        ...
        
    @abstractmethod
    async def import_models(self, source_paths: List[Path]) -> CADModelImportResult:
        """Import CAD models from source paths.
        
        Args:
            source_paths: Paths to import CAD models from (zip files, directories, etc.)
            
        Returns:
            CADModelImportResult with results
            
        Raises:
            Exception: If import fails
        """
        ...


class SnapMagicImportProvider(CADModelProvider):
    """CAD model provider that imports from SnapMagic files.
    
    This provider handles importing KiCad files (.kicad_mod, .kicad_sym) 
    from SnapMagic downloads.
    """
    
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        governed_context: GovernedExecutionContext | None = None,
    ):
        """Initialize the SnapMagic import provider.
        
        Args:
            cache_dir: Directory to store cached imported files
        """
        self._name = "SnapMagicImportProvider"
        self._capabilities = {
            CADModelCapability.FOOTPRINTS,
            CADModelCapability.SYMBOLS
        }
        
        # Default cache directory
        if cache_dir is None:
            cache_dir = Path.home() / ".volta" / "cache" / "snapmagic"
        self._cache_dir = self._prepare_cache_dir(cache_dir)
        self._governed_context = governed_context
        
    @property
    def name(self) -> str:
        """Get the name of this CAD model provider."""
        return self._name
    
    @property  
    def capabilities(self) -> Set[CADModelCapability]:
        """Get the set of capabilities this provider offers."""
        return self._capabilities
    
    async def import_models(self, source_paths: List[Path]) -> CADModelImportResult:
        """Import KiCad models from SnapMagic zip files or directories.
        
        Args:
            source_paths: Paths to import CAD models from
            
        Returns:
            CADModelImportResult with results
        """
        imported_components = []
        errors = []
        warnings = []
        metadata = {}
        
        try:
            for source_path in source_paths:
                try:
                    # Process each source - typically zip files or directories with KiCad files
                    components = await self._process_source(source_path)
                    if self._governed_context is not None and components:
                        governed_result = run_governed_import(
                            context=self._governed_context,
                            source_path=source_path,
                            imported_components=components,
                        )
                        metadata[f"governed_{source_path.name}"] = {
                            "capability_name": governed_result.invocation.capability_name,
                            "status": governed_result.status.value,
                            "evidence_count": len(governed_result.evidence),
                            "object_count": len(governed_result.payload["governed_objects"]),
                        }
                    imported_components.extend(components)
                    
                    # Add metadata about this import
                    metadata[f"source_{source_path.name}"] = {
                        "count": len(components),
                        "success": True
                    }
                except Exception as e:
                    error_msg = f"Failed to import from {source_path}: {str(e)}"
                    errors.append(error_msg)
                    metadata[f"source_{source_path.name}"] = {
                        "count": 0,
                        "success": False,
                        "error": str(e)
                    }
        except Exception as e:
            errors.append(f"Import process failed: {str(e)}")
            
        return CADModelImportResult(
            success=len(errors) == 0,
            imported_components=imported_components,
            errors=errors,
            warnings=warnings,
            metadata=metadata
        )
    
    async def _process_source(self, source_path: Path) -> List[dict]:
        """Process a single source path for KiCad files.
        
        Args:
            source_path: Path to source (zip file, directory, or individual file)
            
        Returns:
            List of imported components
        """
        imported_components = []
        
        # In a real implementation, this would:
        # 1. Handle zip files - extract KiCad files
        # 2. Handle directories 
        # 3. Parse .kicad_mod and .kicad_sym files
        # 4. Extract metadata (MPNs from filenames, component details)
        # 5. Validate against KiCad format specification
        # 6. Cache the files permanently
        
        if source_path.is_dir():
            # Process directory - recursively find KiCad files
            kicad_files = list(source_path.rglob("*.[kK][iI][cC][aA][dD]_[mM][oO][dD]")) + \
                         list(source_path.rglob("*.[kK][iI][cC][aA][dD]_[sS][yY][mM]"))
            for file_path in kicad_files:
                component_data = self._parse_kicad_file(file_path)
                if component_data:
                    imported_components.append(component_data)
        else:
            # Handle individual files or zip file
            if source_path.suffix.lower() in ['.zip']:
                # Extract and process zip file
                # Note: This would require zipfile library
                pass
            elif source_path.suffix.lower() in ['.kicad_mod', '.kicad_sym']:
                # Process single KiCad file
                component_data = self._parse_kicad_file(source_path)
                if component_data:
                    imported_components.append(component_data)
                    
        return imported_components
    
    def _parse_kicad_file(self, file_path: Path) -> Optional[dict]:
        """Parse a single KiCad file and extract component data.
        
        Args:
            file_path: Path to .kicad_mod or .kicad_sym file
            
        Returns:
            Component data dict if successfully parsed, None if not
        """
        try:
            # Read the file content
            content = file_path.read_text(encoding="utf-8")
            
            # In a real implementation, you would parse the S-expression format
            # and extract relevant metadata like:
            # - Component reference (like "R1", "C1")
            # - MPN from filename or attributes
            # - Package type
            # - Pin count
            # - Dimensions
            
            # For demonstration purposes, we'll create dummy component data
            basename = file_path.stem
            mpn = basename  # In real implementation, would extract from filename convention
            
            component_data = {
                "mpn": mpn,
                "file_path": str(file_path),
                "type": "kicad_component",
                "supplier": "snapmagic-import",
                "file_kind": file_path.suffix.lower(),
            }
            
            return component_data
        except Exception:
            # Could not parse the file
            return None

    @staticmethod
    def _prepare_cache_dir(cache_dir: Path) -> Path:
        """Create a writable cache directory, falling back to temp if needed."""
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            return cache_dir
        except PermissionError:
            fallback = Path(tempfile.gettempdir()) / "volta" / "cache" / "snapmagic"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback
