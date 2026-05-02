from fastapi import APIRouter, HTTPException, status
from app.schemas.contact import ContactFormRequest
from app.services.email_service import EmailService
import asyncio

router = APIRouter()

@router.post("")
async def submit_contact_form(payload: ContactFormRequest):
    """Submit the contact form and send an email."""
    try:
        # Fire and forget the email sending to not block the response
        asyncio.create_task(
            EmailService.send_contact_email(
                name=payload.name,
                email=payload.email,
                subject=payload.subject,
                message=payload.message
            )
        )
        return {"message": "Contact form submitted successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit contact form"
        )
