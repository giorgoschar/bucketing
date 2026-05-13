"""
Auth routes: login, logout, first-run setup wizard, invite join.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Household, HouseholdMember, Invitation, MemberRole
from app.auth import (
    hash_password, verify_password, set_session, clear_session,
    get_current_session,
)
from app.seed import seed_categories
from app.templates import templates

router = APIRouter()


def _is_first_run(db: Session) -> bool:
    return db.query(User).count() == 0


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)):
    if _is_first_run(db):
        return RedirectResponse("/setup", status_code=302)
    session = get_current_session(request)
    if session:
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/login", status_code=302)


# ---------------------------------------------------------------------------
# Setup wizard (first run only)
# ---------------------------------------------------------------------------

@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, db: Session = Depends(get_db)):
    if not _is_first_run(db):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("auth/setup.html", {"request": request})


@router.post("/setup", response_class=HTMLResponse)
def setup_submit(
    request: Request,
    household_name: str = Form(...),
    display_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if not _is_first_run(db):
        return RedirectResponse("/login", status_code=302)

    if len(password) < 6:
        return templates.TemplateResponse(
            "auth/setup.html",
            {"request": request, "error": "Password must be at least 6 characters."},
        )

    # Create household
    household = Household(name=household_name.strip())
    db.add(household)
    db.flush()

    # Create user
    user = User(
        username=username.strip().lower(),
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        avatar_color="#6366f1",
    )
    db.add(user)
    db.flush()

    # Add as owner
    db.add(HouseholdMember(
        household_id=household.id,
        user_id=user.id,
        role=MemberRole.owner,
    ))

    db.commit()
    seed_categories(db, household.id)

    response = RedirectResponse("/dashboard", status_code=302)
    set_session(response, user.id, household.id)
    return response


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if _is_first_run(db):
        return RedirectResponse("/setup", status_code=302)
    session = get_current_session(request)
    if session:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("auth/login.html", {"request": request})


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter_by(username=username.strip().lower()).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Invalid username or password."},
        )

    # Pick first household the user belongs to
    membership = (
        db.query(HouseholdMember).filter_by(user_id=user.id).first()
    )
    if not membership:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "You don't belong to any household. Ask for an invite."},
        )

    response = RedirectResponse("/dashboard", status_code=302)
    set_session(response, user.id, membership.household_id)
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=302)
    clear_session(response)
    return response


# ---------------------------------------------------------------------------
# Household switcher
# ---------------------------------------------------------------------------

@router.post("/household/switch", response_class=HTMLResponse)
def switch_household(
    request: Request,
    household_id: str = Form(...),
    db: Session = Depends(get_db),
):
    session = get_current_session(request)
    if not session:
        return RedirectResponse("/login", status_code=302)

    # Verify the user actually belongs to that household
    user = db.get(User, session["user_id"])
    membership = db.query(HouseholdMember).filter_by(
        user_id=user.id, household_id=household_id
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of that household")

    response = RedirectResponse("/dashboard", status_code=302)
    set_session(response, user.id, household_id)
    return response


# ---------------------------------------------------------------------------
# Invite: join a household
# ---------------------------------------------------------------------------

@router.get("/join/{token}", response_class=HTMLResponse)
def join_page(token: str, request: Request, db: Session = Depends(get_db)):
    invite = db.query(Invitation).filter_by(token=token).first()
    if not invite or invite.used_at:
        return templates.TemplateResponse(
            "auth/invite_invalid.html", {"request": request}
        )
    if invite.expires_at and invite.expires_at < datetime.utcnow():
        return templates.TemplateResponse(
            "auth/invite_invalid.html", {"request": request, "expired": True}
        )
    return templates.TemplateResponse(
        "auth/join.html",
        {"request": request, "invite": invite, "household": invite.household},
    )


@router.post("/join/{token}", response_class=HTMLResponse)
def join_submit(
    token: str,
    request: Request,
    display_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    invite = db.query(Invitation).filter_by(token=token).first()
    if not invite or invite.used_at:
        raise HTTPException(status_code=400, detail="Invalid invite")
    if invite.expires_at and invite.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invite expired")

    if len(password) < 6:
        return templates.TemplateResponse(
            "auth/join.html",
            {
                "request": request,
                "invite": invite,
                "household": invite.household,
                "error": "Password must be at least 6 characters.",
            },
        )

    existing = db.query(User).filter_by(username=username.strip().lower()).first()
    if existing:
        return templates.TemplateResponse(
            "auth/join.html",
            {
                "request": request,
                "invite": invite,
                "household": invite.household,
                "error": "Username already taken.",
            },
        )

    user = User(
        username=username.strip().lower(),
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        avatar_color="#ec4899",
    )
    db.add(user)
    db.flush()

    db.add(HouseholdMember(
        household_id=invite.household_id,
        user_id=user.id,
        role=MemberRole.member,
    ))

    invite.used_at = datetime.utcnow()
    invite.used_by = user.id
    db.commit()

    response = RedirectResponse("/dashboard", status_code=302)
    set_session(response, user.id, invite.household_id)
    return response
