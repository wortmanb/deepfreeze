"""Action API routes (mutating operations)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from ..models.commands import (
    CleanupRequest,
    RefreezeRequest,
    RepairRequest,
    RotateRequest,
    SetupRequest,
    ThawCheckRequest,
    ThawCreateRequest,
)
from ..orchestration.orchestrator import DeepfreezeOrchestrator
from .deps import get_orchestrator

router = APIRouter()


@router.post("/actions/rotate")
async def rotate(
    body: RotateRequest,
    orch: DeepfreezeOrchestrator = Depends(get_orchestrator),
):
    """Execute rotate action."""
    result = await orch.rotate(
        year=body.year,
        month=body.month,
        keep=body.keep,
        dry_run=body.dry_run,
    )
    return result.model_dump()


@router.post("/actions/thaw")
async def thaw_create(
    body: ThawCreateRequest,
    orch: DeepfreezeOrchestrator = Depends(get_orchestrator),
):
    """Create a new thaw request."""
    try:
        start = datetime.fromisoformat(body.start_date)
        end = datetime.fromisoformat(body.end_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {e}")

    result = await orch.thaw_create(
        start_date=start,
        end_date=end,
        duration=body.duration,
        tier=body.tier,
        sync=body.sync,
        dry_run=body.dry_run,
    )
    return result.model_dump()


@router.post("/actions/thaw/check")
async def thaw_check(
    body: ThawCheckRequest,
    orch: DeepfreezeOrchestrator = Depends(get_orchestrator),
):
    """Check thaw request status."""
    result = await orch.thaw_check(request_id=body.request_id)
    return result.model_dump()


@router.post("/actions/refreeze")
async def refreeze(
    body: RefreezeRequest,
    orch: DeepfreezeOrchestrator = Depends(get_orchestrator),
):
    """Refreeze thawed data."""
    result = await orch.refreeze(
        request_id=body.request_id,
        dry_run=body.dry_run,
    )
    return result.model_dump()


@router.post("/actions/cleanup")
async def cleanup(
    body: CleanupRequest,
    orch: DeepfreezeOrchestrator = Depends(get_orchestrator),
):
    """Clean up expired repos and old thaw requests."""
    result = await orch.cleanup(
        refrozen_retention_days=body.refrozen_retention_days,
        dry_run=body.dry_run,
    )
    return result.model_dump()


@router.post("/actions/repair")
async def repair_metadata(
    body: RepairRequest,
    orch: DeepfreezeOrchestrator = Depends(get_orchestrator),
):
    """Repair metadata inconsistencies."""
    result = await orch.repair_metadata(dry_run=body.dry_run)
    return result.model_dump()


@router.post("/actions/setup")
async def setup(
    body: SetupRequest,
    orch: DeepfreezeOrchestrator = Depends(get_orchestrator),
):
    """Initialize deepfreeze."""
    result = await orch.setup(
        repo_name_prefix=body.repo_name_prefix,
        bucket_name_prefix=body.bucket_name_prefix,
        ilm_policy_name=body.ilm_policy_name,
        index_template_name=body.index_template_name,
        dry_run=body.dry_run,
    )
    return result.model_dump()
