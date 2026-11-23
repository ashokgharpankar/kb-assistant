from collections.abc import Iterator

import pytest

from kb_api import main
from kb_api.auth import get_verifier


@pytest.fixture(autouse=True)
def _overrides() -> Iterator[None]:
    """Each test starts with auth disabled and no pipeline; tests set what they need."""
    main.app.dependency_overrides[get_verifier] = lambda: None
    yield
    main.app.dependency_overrides.clear()
