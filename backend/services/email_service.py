"""
Email delivery via Resend.
Two surfaces:
  - Alert emails (immediate, triggered by alert_checker node for high/critical)
  - Daily digest emails (batched, triggered by digest_job)
"""
import structlog
import resend
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

logger = structlog.get_logger()


def _get_resend_client() -> None:
    """Configure Resend API key (must be called before any send)."""
    settings = get_settings()
    resend.api_key = settings.resend_api_key


# ---------------------------------------------------------------------------
# Alert emails
# ---------------------------------------------------------------------------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=5, max=30))
async def send_alert_email(user_id: str, alert) -> None:
    """Send an immediate alert email for high/critical severity alerts."""
    _get_resend_client()
    settings = get_settings()

    from database.connection import AsyncSessionLocal
    from models.user import User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == alert.user_id))).scalar_one_or_none()
        if not user or not user.email:
            logger.warning("send_alert_email: user not found or no email", user_id=user_id)
            return

    severity_emoji = {"critical": "🚨", "high": "⚠️", "medium": "📌", "low": "💡"}.get(
        alert.severity, "📌"
    )

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="background: #1a1a2e; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
    <h1 style="margin: 0; font-size: 20px;">Hedge Fund Intelligence Platform</h1>
  </div>
  <div style="background: #f8f9fa; padding: 20px; border: 1px solid #e9ecef;">
    <h2 style="color: #343a40;">{severity_emoji} {alert.title}</h2>
    <p style="color: #6c757d; font-size: 14px;">
      Severity: <strong style="color: {'#dc3545' if alert.severity == 'critical' else '#fd7e14' if alert.severity == 'high' else '#343a40'};">{alert.severity.upper()}</strong>
      &nbsp;|&nbsp; Score: {alert.score}/100
    </p>
    <p style="color: #343a40; line-height: 1.6;">{alert.summary or ''}</p>
    <a href="{settings.frontend_url}/alerts" style="
      display: inline-block; background: #4f46e5; color: white;
      padding: 10px 20px; border-radius: 6px; text-decoration: none; margin-top: 16px;
    ">View Alert</a>
  </div>
  <div style="background: #e9ecef; padding: 12px 20px; border-radius: 0 0 8px 8px;">
    <p style="color: #6c757d; font-size: 12px; margin: 0;">
      You're receiving this because you track this investor.
      <a href="{settings.frontend_url}/settings">Manage notifications</a>
    </p>
  </div>
</body>
</html>
"""

    try:
        resend.Emails.send({
            "from": "alerts@akshat21.me",
            "to": [user.email],
            "subject": f"{severity_emoji} {alert.title}",
            "html": html_body,
        })
        logger.info("Alert email sent", alert_id=str(alert.id), user_email=user.email)
    except Exception as e:
        logger.error("Failed to send alert email", error=str(e), alert_id=str(alert.id))
        raise


# ---------------------------------------------------------------------------
# Daily digest emails
# ---------------------------------------------------------------------------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=5, max=30))
async def send_digest_email(user_email: str, user_name: str | None, report_markdown: str, report_id: str) -> None:
    """Send the daily digest email."""
    _get_resend_client()
    settings = get_settings()

    display_name = user_name or "there"

    # Convert markdown headings to simple HTML (minimal, not full md-to-html)
    lines = []
    for line in report_markdown.splitlines():
        if line.startswith("## "):
            lines.append(f"<h3 style='color:#1a1a2e;margin-top:20px;'>{line[3:]}</h3>")
        elif line.startswith("# "):
            lines.append(f"<h2 style='color:#1a1a2e;'>{line[2:]}</h2>")
        elif line.startswith("- "):
            lines.append(f"<li>{line[2:]}</li>")
        elif line.strip():
            lines.append(f"<p style='color:#343a40;line-height:1.6;'>{line}</p>")
        else:
            lines.append("<br>")
    content_html = "\n".join(lines)

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="background: #1a1a2e; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
    <h1 style="margin: 0; font-size: 20px;">📊 Your Daily Hedge Fund Digest</h1>
  </div>
  <div style="background: #f8f9fa; padding: 20px; border: 1px solid #e9ecef;">
    <p>Hi {display_name},</p>
    <p>Here's your daily intelligence digest:</p>
    {content_html}
    <a href="{settings.frontend_url}/reports/{report_id}" style="
      display: inline-block; background: #4f46e5; color: white;
      padding: 10px 20px; border-radius: 6px; text-decoration: none; margin-top: 16px;
    ">View Full Report</a>
  </div>
  <div style="background: #e9ecef; padding: 12px 20px; border-radius: 0 0 8px 8px;">
    <p style="color: #6c757d; font-size: 12px; margin: 0;">
      <a href="{settings.frontend_url}/settings">Manage email preferences</a>
    </p>
  </div>
</body>
</html>
"""

    try:
        resend.Emails.send({
            "from": "digest@akshat21.me",
            "to": [user_email],
            "subject": "📊 Your Daily Hedge Fund Intelligence Digest",
            "html": html_body,
        })
        logger.info("Digest email sent", user_email=user_email, report_id=report_id)
    except Exception as e:
        logger.error("Failed to send digest email", error=str(e), user_email=user_email)
        raise
