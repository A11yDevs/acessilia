import pytest

from scripts.check_image_size import parse_docker_size


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0B", 0), ("512kB", 512_000), ("1.5GB", 1_500_000_000)],
)
def test_parse_docker_size(value: str, expected: int) -> None:
    assert parse_docker_size(value) == expected


def test_parse_docker_size_rejects_unknown_units() -> None:
    with pytest.raises(ValueError):
        parse_docker_size("2GiB")