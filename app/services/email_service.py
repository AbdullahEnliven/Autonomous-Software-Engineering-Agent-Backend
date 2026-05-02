import smtplib
from email.message import EmailMessage
from email.utils import formataddr
import asyncio
from typing import Optional

from app.config import settings

class EmailService:
    @staticmethod
    def _get_base_template(content: str, title: str) -> str:
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{title}</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                    background-color: #f6f1e8;
                    color: #10131b;
                    margin: 0;
                    padding: 0;
                }}
                .container {{
                    max-width: 600px;
                    margin: 40px auto;
                    background-color: #10131b;
                    border-radius: 12px;
                    overflow: hidden;
                    box-shadow: 0 20px 40px rgba(16, 19, 27, 0.2);
                }}
                .header {{
                    background-color: #10131b;
                    padding: 32px 40px;
                    text-align: left;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
                }}
                .logo {{
                    color: #fff;
                    font-size: 24px;
                    font-weight: 900;
                    letter-spacing: -0.5px;
                    text-decoration: none;
                }}
                .logo-subtitle {{
                    display: block;
                    font-size: 10px;
                    font-weight: 900;
                    text-transform: uppercase;
                    letter-spacing: 0.2em;
                    color: #007f75;
                    margin-top: 4px;
                }}
                .content {{
                    background-color: #10131b;
                    padding: 40px;
                    color: rgba(255, 255, 255, 0.85);
                    line-height: 1.6;
                    font-size: 16px;
                }}
                h1 {{
                    color: #fff;
                    font-size: 28px;
                    font-weight: 900;
                    margin-top: 0;
                    margin-bottom: 24px;
                    letter-spacing: -0.5px;
                }}
                p {{
                    margin-top: 0;
                    margin-bottom: 24px;
                }}
                .btn {{
                    display: inline-block;
                    background-color: #f6c453;
                    color: #10131b !important;
                    text-decoration: none;
                    font-weight: 900;
                    padding: 14px 28px;
                    border-radius: 8px;
                    font-size: 15px;
                    margin-bottom: 24px;
                }}
                .footer {{
                    background-color: #0a0c11;
                    padding: 32px 40px;
                    text-align: center;
                    font-size: 13px;
                    color: rgba(255, 255, 255, 0.4);
                }}
                .accent-text {{
                    color: #007f75;
                    font-weight: bold;
                }}
                .highlight-box {{
                    background-color: rgba(255, 255, 255, 0.05);
                    border-left: 4px solid #007f75;
                    padding: 20px;
                    border-radius: 4px;
                    margin-bottom: 24px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <a href="{settings.FRONTEND_URL}" class="logo">ASEA</a>
                    <span class="logo-subtitle">build room</span>
                </div>
                <div class="content">
                    {content}
                </div>
                <div class="footer">
                    <p>&copy; {datetime.now().year} ASEA. All rights reserved.</p>
                    <p>You received this email because it's related to your ASEA account.</p>
                </div>
            </div>
        </body>
        </html>
        """

    @staticmethod
    def _send_email_sync(to_email: str, subject: str, html_content: str, reply_to: Optional[str] = None):
        if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
            print(f"WARN: SMTP credentials not set. Would have sent email to {to_email} with subject: {subject}")
            return

        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = formataddr(("ASEA", settings.EMAIL_FROM))
        msg['To'] = to_email
        if reply_to:
            msg['Reply-To'] = reply_to

        msg.set_content("Please enable HTML to view this email.")
        msg.add_alternative(html_content, subtype='html')

        try:
            with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
                if settings.SMTP_PORT == 587:
                    server.starttls()
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                server.send_message(msg)
        except Exception as e:
            print(f"Error sending email to {to_email}: {e}")

    @staticmethod
    async def _send_email_async(to_email: str, subject: str, html_content: str, reply_to: Optional[str] = None):
        await asyncio.to_thread(EmailService._send_email_sync, to_email, subject, html_content, reply_to)

    @staticmethod
    async def send_welcome_email(to_email: str, name: str = ""):
        title = "Welcome to ASEA"
        name_greeting = f" {name}" if name else ""
        
        content = f"""
            <h1>Welcome to the build room{name_greeting}.</h1>
            <p>Your ASEA account is ready. We're excited to have you on board to shape the future of AI-powered commerce development.</p>
            
            <div class="highlight-box">
                <p style="margin-bottom: 0;"><strong>Beta Access Activated:</strong> You currently have full access to generate, edit, and export up to 5 complete projects at no cost.</p>
            </div>
            
            <p>Ready to build your first storefront?</p>
            
            <a href="{settings.FRONTEND_URL}/dashboard" class="btn">Go to Dashboard</a>
            
            <p>If you have any questions, simply reply to this email. Our team is here to help you get the most out of the beta.</p>
        """
        
        html = EmailService._get_base_template(content, title)
        await EmailService._send_email_async(to_email, title, html)

    @staticmethod
    async def send_verification_email(to_email: str, token: str):
        title = "Verify your email address"
        verification_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
        
        content = f"""
            <h1>Verify your email.</h1>
            <p>Please confirm your email address to secure your ASEA account and get started building.</p>
            
            <a href="{verification_url}" class="btn">Verify Email</a>
            
            <p style="font-size: 13px; color: rgba(255,255,255,0.5);">
                Or copy and paste this link into your browser:<br>
                <a href="{verification_url}" style="color: #007f75; text-decoration: none;">{verification_url}</a>
            </p>
            <p style="font-size: 13px; color: rgba(255,255,255,0.5);">If you didn't create an account with us, you can safely ignore this email.</p>
        """
        
        html = EmailService._get_base_template(content, title)
        await EmailService._send_email_async(to_email, title, html)

    @staticmethod
    async def send_reset_password_email(to_email: str, token: str):
        title = "Reset your password"
        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        
        content = f"""
            <h1>Reset your password.</h1>
            <p>We received a request to reset the password for your ASEA account. Click the button below to choose a new password.</p>
            
            <a href="{reset_url}" class="btn">Reset Password</a>
            
            <p style="font-size: 13px; color: rgba(255,255,255,0.5);">
                This link will expire in 1 hour.<br><br>
                Or copy and paste this link into your browser:<br>
                <a href="{reset_url}" style="color: #007f75; text-decoration: none;">{reset_url}</a>
            </p>
            <p style="font-size: 13px; color: rgba(255,255,255,0.5);">If you didn't request a password reset, you can safely ignore this email. Your password will remain unchanged.</p>
        """
        
        html = EmailService._get_base_template(content, title)
        await EmailService._send_email_async(to_email, title, html)

    @staticmethod
    async def send_contact_email(name: str, email: str, subject: str, message: str):
        to_email = settings.CONTACT_EMAIL
        if not to_email:
            print("WARN: CONTACT_EMAIL not set. Skipping contact form email.")
            return

        title = "New Contact Form Submission"
        
        content = f"""
            <h1>New message from {name}.</h1>
            
            <div class="highlight-box" style="border-left-color: #f6c453;">
                <p style="margin-bottom: 8px;"><strong style="color: rgba(255,255,255,0.5);">Name:</strong> {name}</p>
                <p style="margin-bottom: 8px;"><strong style="color: rgba(255,255,255,0.5);">Email:</strong> {email}</p>
                <p style="margin-bottom: 0;"><strong style="color: rgba(255,255,255,0.5);">Subject:</strong> {subject}</p>
            </div>
            
            <h3 style="margin-top: 30px; margin-bottom: 16px; color: #fff;">Message:</h3>
            <div style="background-color: rgba(255,255,255,0.02); padding: 20px; border-radius: 8px; white-space: pre-wrap;">
{message}
            </div>
        """
        
        html = EmailService._get_base_template(content, title)
        # Reply-to the person who filled out the contact form
        await EmailService._send_email_async(to_email, f"ASEA Contact: {subject}", html, reply_to=email)

from datetime import datetime
