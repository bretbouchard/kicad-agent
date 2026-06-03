"""Library operation schemas -- add, remove, list, and update library entries."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from kicad_agent.ops.schema import (
    TargetFile,
    _validate_safe_identifier,
)


class AddLibEntryOp(BaseModel):
    """Add a library entry to sym-lib-table or fp-lib-table.

    Attributes:
        op_type: Discriminator literal ``"add_lib_entry"``.
        target_file: Relative path to sym-lib-table or fp-lib-table.
        lib_name: Library name (e.g. ``"Device"``, ``"MyLib"``).
        lib_type: Library type (``"KiCad"`` or ``"Legacy"``).
        uri: Library URI path, may contain variables like ``${KIPRJMOD}``.
        options: Library options string (usually empty).
        description: Library description.
    """

    op_type: Literal["add_lib_entry"] = "add_lib_entry"
    target_file: TargetFile
    lib_name: str = Field(
        min_length=1,
        max_length=128,
        description="Library name",
    )
    lib_type: Literal["KiCad", "Legacy"] = "KiCad"
    uri: str = Field(
        min_length=1,
        max_length=512,
        description="Library URI path",
    )
    options: str = Field(default="", max_length=256)
    description: str = Field(default="", max_length=512)

    @field_validator("lib_name")
    @classmethod
    def _validate_lib_name(cls, v: str) -> str:
        return _validate_safe_identifier(v, "lib_name")


class RemoveLibEntryOp(BaseModel):
    """Remove a library entry from sym-lib-table or fp-lib-table.

    Attributes:
        op_type: Discriminator literal ``"remove_lib_entry"``.
        target_file: Relative path to sym-lib-table or fp-lib-table.
        lib_name: Library name to remove.
    """

    op_type: Literal["remove_lib_entry"] = "remove_lib_entry"
    target_file: TargetFile
    lib_name: str = Field(
        min_length=1,
        max_length=128,
        description="Library name to remove",
    )

    @field_validator("lib_name")
    @classmethod
    def _validate_lib_name(cls, v: str) -> str:
        return _validate_safe_identifier(v, "lib_name")


class ListLibEntriesOp(BaseModel):
    """List all library entries in a sym-lib-table or fp-lib-table.

    Read-only operation -- returns all entries without modifying the file.

    Attributes:
        op_type: Discriminator literal ``"list_lib_entries"``.
        target_file: Relative path to sym-lib-table or fp-lib-table.
    """

    op_type: Literal["list_lib_entries"] = "list_lib_entries"
    target_file: TargetFile


class UpdateSymbolsFromLibraryOp(BaseModel):
    """Re-embed all mismatched symbols from their libraries.

    Equivalent to KiCad GUI's "Update Symbol from Library" for all symbols
    whose embedded lib_symbols definition diverges from the library version.

    Attributes:
        op_type: Discriminator literal ``"update_symbols_from_library"``.
        target_file: Relative path to the .kicad_sch file.
        references: Optional list of specific references to update. If None, updates all mismatches.
        dry_run: If True, report what would change without modifying the file.
    """

    op_type: Literal["update_symbols_from_library"] = "update_symbols_from_library"
    target_file: TargetFile
    references: Optional[list[str]] = Field(
        default=None,
        description="Specific references to update, or None for all mismatches",
    )
    dry_run: bool = Field(
        default=False,
        description="Report mismatches without modifying the file",
    )
