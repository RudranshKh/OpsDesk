from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_roles
from app.api.schemas.routing import RoutingProfileRead, RoutingProfileUpdate
from app.api.schemas.tickets import AgencyOption, UserOption
from app.db.models import AgentProfile, Agency, User

router = APIRouter(tags=["directory"])


@router.get("/agencies", response_model=list[AgencyOption])
def list_agencies(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Agency]:
    return list(db.scalars(select(Agency).where(Agency.id == user.agency_id)).all())


@router.get("/users", response_model=list[UserOption])
def list_users(
    agency_id: int | None = Query(default=None, gt=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[User]:
    if agency_id is not None and agency_id != user.agency_id:
        raise HTTPException(status_code=403, detail="You cannot access users from another agency")
    statement = select(User).where(
        User.agency_id == user.agency_id, User.is_active.is_(True)
    ).order_by(User.full_name)
    return list(db.scalars(statement).all())


@router.get("/users/{user_id}/routing-profile", response_model=RoutingProfileRead)
def get_routing_profile(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoutingProfileRead:
    user = db.scalar(select(User).where(User.id == user_id, User.agency_id == current_user.agency_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    profile = user.agent_profile
    return RoutingProfileRead(
        user_id=user.id,
        user_name=user.full_name,
        user_role=user.role,
        regions=profile.regions if profile else [],
        is_available=profile.is_available if profile else False,
        has_profile=profile is not None,
    )


@router.put("/users/{user_id}/routing-profile", response_model=RoutingProfileRead)
def update_routing_profile(
    user_id: int,
    payload: RoutingProfileUpdate,
    current_user: User = Depends(require_roles("admin", "escalation_manager")),
    db: Session = Depends(get_db),
) -> RoutingProfileRead:
    user = db.scalar(select(User).where(User.id == user_id, User.agency_id == current_user.agency_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role not in {"agent", "escalation_manager"}:
        raise HTTPException(status_code=422, detail="Routing profiles are only valid for agents and escalation managers")
    if not user.is_active:
        raise HTTPException(status_code=422, detail="Inactive users cannot be routing candidates")

    profile = user.agent_profile
    if profile is None:
        profile = AgentProfile(user_id=user.id)
        db.add(profile)
    profile.regions = payload.regions
    profile.is_available = payload.is_available
    db.commit()
    db.refresh(profile)
    return RoutingProfileRead(
        user_id=user.id,
        user_name=user.full_name,
        user_role=user.role,
        regions=profile.regions,
        is_available=profile.is_available,
        has_profile=True,
    )
