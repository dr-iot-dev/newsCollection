from app.contracts.acquisition_v1 import AcquisitionResultV1
from app.contracts.article_package_v1 import ArticlePackageV1
from app.contracts.draft_v1 import ArticleDraftV1
from app.contracts.verification_v1 import VerificationReportV1


def test_sensitive_fields_are_absent_from_writer_and_verifier_contracts() -> None:
    forbidden = {"body_text", "raw_html", "authorization", "cookie", "credentials"}
    for model in (ArticlePackageV1, ArticleDraftV1, VerificationReportV1):
        assert forbidden.isdisjoint(model.model_fields)


def test_all_contract_schemas_are_strict() -> None:
    for model in (AcquisitionResultV1, ArticlePackageV1, ArticleDraftV1, VerificationReportV1):
        assert model.model_json_schema()["additionalProperties"] is False
