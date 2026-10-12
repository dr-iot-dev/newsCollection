from unittest.mock import Mock

import pytest

from app.ai.diagnostics import validation_diagnostics
from app.contracts.comparison_selection_v1 import CandidateSuitabilityV1
from app.core.config import Settings
from app.core.editorial import EditorialError
from app.orchestration.featured_images import FeaturedImageService, process_featured_images
from app.orchestration.publication import PublicationService, process_verified_publications


def test_shadow_setting_blocks_wordpress_even_if_legacy_verification_passed():
    session, port = Mock(), Mock()
    settings = Settings(
        _env_file=None,
        wordpress_enabled=True,
        wordpress_base_url="https://cms.example",
        comparison_selection_mode="shadow",
    )
    with pytest.raises(EditorialError, match="COMPARISON_SHADOW_PUBLICATION_DISABLED"):
        PublicationService(session, settings, port)
    assert not port.mock_calls and not session.mock_calls


def test_shadow_setting_blocks_images_and_skips_automatic_remote_work():
    session, port, provider = Mock(), Mock(), Mock()
    settings = Settings(
        _env_file=None,
        wordpress_enabled=True,
        featured_images_enabled=True,
        wordpress_base_url="https://cms.example",
        comparison_selection_mode="shadow",
    )
    assert process_verified_publications(session, settings, port=port) == 0
    assert process_featured_images(session, settings, port=port, provider=provider) == 0
    with pytest.raises(EditorialError, match="COMPARISON_SHADOW_PUBLICATION_DISABLED"):
        FeaturedImageService(session, settings, port=port, provider=provider)
    assert not port.mock_calls and not session.mock_calls and not provider.mock_calls


@pytest.mark.parametrize(
    "code",
    [
        "COMPARISON_GROUNDING_INVALID",
        "COMPARISON_OTHER_PRODUCT_GROUNDING",
        "COMPARISON_CELL_CONDITION_LOST",
        "COMPARISON_REQUIRED_CONDITION_FAILED",
    ],
)
def test_comparison_repair_has_specific_safe_diagnostics(code):
    diagnostic = validation_diagnostics(EditorialError(code), CandidateSuitabilityV1, 1)
    assert diagnostic[0]["code"] == code
    assert "AI_VALIDATION_ERROR" not in str(diagnostic)
