from app.contracts.editorial_v1 import ReviewRequestV1
from app.core.editorial import EditorialError


def validate_checklist(request: ReviewRequestV1) -> None:
    if request.decision == "approve" and not all(request.checklist.model_dump().values()):
        raise EditorialError("REVIEW_CHECKLIST_INCOMPLETE")
