"""Inbound SMS webhooks, one per provider, plus a local simulator.

Provider webhooks parse the form themselves (each provider has its own field
names), then hand off to the same engine.handle_inbound. The engine does
blocking network sends, so async routes push it to the threadpool.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..config import get_settings
from ..db import get_db
from ..engine import handle_inbound
from ..gateways import get_gateway
from ..gateways.twilio import validate_twilio_signature

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


@router.post("/twilio")
async def twilio_inbound(request: Request, db: Session = Depends(get_db)) -> Response:
    form = {k: str(v) for k, v in (await request.form()).items()}
    settings = get_settings()

    if settings.twilio_validate_signature:
        signature = request.headers.get("X-Twilio-Signature", "")
        # Behind ngrok/a proxy the URL Twilio signed is the public one.
        if settings.public_base_url:
            url = settings.public_base_url.rstrip("/") + request.url.path
        else:
            url = str(request.url)
        if not validate_twilio_signature(url, form, signature, settings.twilio_auth_token):
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    sender = form.get("From", "")
    body = form.get("Body", "")
    if sender:
        await run_in_threadpool(handle_inbound, db, sender, body, get_gateway())

    # Replies go out via the REST API (same path as every other provider),
    # so answer Twilio with empty TwiML.
    return Response(content=EMPTY_TWIML, media_type="application/xml")


@router.post("/africastalking")
async def africastalking_inbound(
    request: Request, db: Session = Depends(get_db)
) -> Response:
    form = await request.form()
    sender = str(form.get("from") or "")
    text = str(form.get("text") or "")
    if sender:
        await run_in_threadpool(handle_inbound, db, sender, text, get_gateway())
    return Response(content="OK")


class SimulatedInbound(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    text: str


@router.post("/simulate")
def simulate_inbound(payload: SimulatedInbound, db: Session = Depends(get_db)) -> dict:
    """Pretend a respondent texted us. Local testing only."""
    if not get_settings().enable_simulator:
        raise HTTPException(status_code=404)
    replies = handle_inbound(db, payload.from_, payload.text, get_gateway())
    return {"replies": replies}
