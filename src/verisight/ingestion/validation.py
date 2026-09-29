"""File validation for the VeriSight ingestion subsystem."""

from pathlib import Path

from verisight.ingestion.exceptions import (
    FileValidationError,
    UnsupportedFileTypeError,
)
from verisight.ingestion.models import SourceMetadata

SUPPORTED_FILE_EXTENSIONS = frozenset(
    {
        ".csv",
        ".json",
        ".xls",
        ".xlsx",
    }
)


def validate_file(
    path: str | Path,
    *,
    max_size_mb: int,
) -> SourceMetadata:
    """Validate an input file and return its normalized source metadata."""

    file_path = Path(path).expanduser()

    if not file_path.exists():
        raise FileValidationError(f"File does not exist: {file_path}")

    if not file_path.is_file():
        raise FileValidationError(f"Path is not a file: {file_path}")

    extension = file_path.suffix.lower()

    if extension not in SUPPORTED_FILE_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{extension or '<none>'}'. "
            f"Supported types: {', '.join(sorted(SUPPORTED_FILE_EXTENSIONS))}"
        )

    file_size_bytes = file_path.stat().st_size

    if file_size_bytes == 0:
        raise FileValidationError(f"File is empty: {file_path}")

    max_size_bytes = max_size_mb * 1024 * 1024

    if file_size_bytes > max_size_bytes:
        raise FileValidationError(
            f"File exceeds maximum size of {max_size_mb} MB: {file_path}"
        )

    return SourceMetadata(
        path=file_path,
        file_name=file_path.name,
        file_extension=extension,
        file_size_bytes=file_size_bytes,
    )
