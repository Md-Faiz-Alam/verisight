import pytest

from verisight.exceptions import VeriSightError
from verisight.ingestion.exceptions import (
    DataLoadError,
    FileValidationError,
    IngestionError,
    UnsupportedFileTypeError,
)


@pytest.mark.parametrize(
    "exception_type",
    [
        UnsupportedFileTypeError,
        FileValidationError,
        DataLoadError,
    ],
)
def test_ingestion_exceptions_inherit_from_ingestion_error(
    exception_type: type[IngestionError],
) -> None:
    error = exception_type("Ingestion failed")

    assert isinstance(error, IngestionError)
    assert isinstance(error, VeriSightError)
    assert isinstance(error, Exception)


def test_ingestion_error_preserves_message() -> None:
    error = IngestionError("Could not ingest dataset")

    assert str(error) == "Could not ingest dataset"


def test_specific_ingestion_error_can_be_caught_as_ingestion_error() -> None:
    with pytest.raises(IngestionError, match="Unsupported file type"):
        raise UnsupportedFileTypeError("Unsupported file type")
