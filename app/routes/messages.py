"""Private message routes (per-author, one-time)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..auth import web_user
from ..db import Message, MessageStatus, User, get_session, utcnow

router = APIRouter()


@router.post("/messages")
def add_message(
    text: str = Form(...),
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    text = text.strip()
    if text:
        session.add(Message(author_user_id=user.id, text=text))
        session.commit()
    return RedirectResponse("/?msg=Message+queued", status_code=303)


@router.post("/messages/{message_id}/delete")
def delete_message(
    message_id: int,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    message = session.get(Message, message_id)
    # Only the author may delete, and only while still pending.
    if (
        message is not None
        and message.author_user_id == user.id
        and message.status == MessageStatus.pending
    ):
        session.delete(message)
        session.commit()
    return RedirectResponse("/?msg=Message+deleted", status_code=303)
