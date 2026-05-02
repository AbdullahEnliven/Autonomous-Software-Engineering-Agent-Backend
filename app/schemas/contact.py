from pydantic import BaseModel, EmailStr

class ContactFormRequest(BaseModel):
    name: str
    email: EmailStr
    subject: str
    message: str
