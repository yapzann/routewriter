import os
import logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

logger = logging.getLogger(__name__)

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL       = os.environ.get("FROM_EMAIL", "")
COMPANY_NAME     = os.environ.get("COMPANY_NAME", "Your Company")


def _is_configured() -> bool:
    return bool(SENDGRID_API_KEY and FROM_EMAIL)


def send_reminder(customer) -> bool:
    """
    Send a maintenance reminder email to a single customer.
    Returns True on success, False on failure.
    Raises RuntimeError if SendGrid is not configured.
    """
    if not _is_configured():
        raise RuntimeError(
            "Email is not configured. Set SENDGRID_API_KEY and FROM_EMAIL environment variables."
        )

    if not customer.email:
        logger.warning("Customer '%s' has no email address — skipping.", customer.name)
        return False

    last_service = (
        customer.last_service_date.strftime("%B %d, %Y")
        if customer.last_service_date
        else "not yet on record"
    )

    subject = f"Time for your annual HVAC service, {customer.name.split()[0]}!"

    html_body = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
                max-width:560px;margin:0 auto;color:#1e293b;">
      <div style="background:#1a6fc4;padding:18px 24px;border-radius:8px 8px 0 0;">
        <h2 style="color:#fff;margin:0;font-size:18px;">{COMPANY_NAME}</h2>
      </div>
      <div style="background:#f8fafc;padding:28px 24px;border-radius:0 0 8px 8px;
                  border:1px solid #e2e8f0;border-top:none;">
        <p style="margin:0 0 14px;">Hi <strong>{customer.name}</strong>,</p>
        <p style="margin:0 0 14px;">
          It's been almost a year since your last HVAC service
          (<strong>{last_service}</strong>), and we wanted to reach out to
          schedule your annual maintenance visit.
        </p>
        <p style="margin:0 0 14px;">
          Regular HVAC servicing keeps your system running efficiently, extends
          its life, and helps you avoid costly emergency repairs.
        </p>
        <p style="margin:0 0 22px;">
          Give us a call or reply to this email and we'll get you booked in at
          a time that works for you.
        </p>
        <p style="margin:0;color:#475569;font-size:14px;">
          Warm regards,<br/>
          <strong>{COMPANY_NAME}</strong>
        </p>
      </div>
      <p style="text-align:center;font-size:12px;color:#94a3b8;margin-top:16px;">
        You're receiving this because you're a valued customer of {COMPANY_NAME}.
      </p>
    </div>
    """

    plain_body = (
        f"Hi {customer.name},\n\n"
        f"It's been almost a year since your last HVAC service ({last_service}), "
        f"and we wanted to reach out to schedule your annual maintenance visit.\n\n"
        f"Regular HVAC servicing keeps your system running efficiently, extends its "
        f"life, and helps you avoid costly emergency repairs.\n\n"
        f"Give us a call or reply to this email to get booked in.\n\n"
        f"Warm regards,\n{COMPANY_NAME}"
    )

    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=customer.email,
        subject=subject,
        plain_text_content=plain_body,
        html_content=html_body,
    )

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info(
            "Reminder sent to %s (%s) — status %s",
            customer.name, customer.email, response.status_code,
        )
        return response.status_code in (200, 202)
    except Exception as exc:
        logger.error("Failed to send reminder to %s: %s", customer.email, exc)
        return False


def send_reminders_bulk(customers) -> dict:
    """
    Send reminders to a list of customers.
    Returns {"sent": N, "skipped": M, "errors": K}
    """
    sent = skipped = errors = 0
    for c in customers:
        if not c.email:
            skipped += 1
            continue
        try:
            ok = send_reminder(c)
            if ok:
                sent += 1
            else:
                errors += 1
        except RuntimeError:
            raise
        except Exception:
            errors += 1
    return {"sent": sent, "skipped": skipped, "errors": errors}
