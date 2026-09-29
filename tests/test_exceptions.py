import pytest

from verisight.exceptions import ConfigurationError, VeriSightError


def test_verisight_error_is_an_exception() -> None:
    error = VeriSightError("Something went wrong")

    assert isinstance(error, Exception)
    assert str(error) == "Something went wrong"


def test_configuration_error_inherits_from_verisight_error() -> None:
    error = ConfigurationError("Invalid configuration")

    assert isinstance(error, VeriSightError)
    assert isinstance(error, Exception)


def test_configuration_error_can_be_caught_as_verisight_error() -> None:
    with pytest.raises(VeriSightError, match="Invalid configuration"):
        raise ConfigurationError("Invalid configuration")
