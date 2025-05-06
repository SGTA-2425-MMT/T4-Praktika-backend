from fastapi import APIRouter
from typing import List
from app.schemas import ScenarioOut
from app.db import db

router = APIRouter(prefix="/api/scenarios", tags=["Scenarios"])


@router.get("", response_model=List[ScenarioOut])
async def list_scenarios():
    """
    Return all saved scenarios.
    """
    cursor = db.scenarios.find()
    scenarios = []
    async for doc in cursor:
        scenarios.append(doc)
    return scenarios
