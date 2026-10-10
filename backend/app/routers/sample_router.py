from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.data.seed import create_sample_case
from app.schemas import schemas

router = APIRouter(prefix="/api/sample-case", tags=["sample"])


@router.post("", response_model=schemas.CaseSummary)
def load_sample_case(db: Session = Depends(get_db)):
    """Create the fictional demo case on request. Idempotent."""
    return create_sample_case(db)
