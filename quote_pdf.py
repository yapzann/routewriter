import os
from datetime import date
from fpdf import FPDF

COMPANY_NAME = os.environ.get("COMPANY_NAME", "Your Company")

# ── Colour palette ────────────────────────────────────────────────────────────
BLUE       = (26,  111, 196)   # brand blue
BLUE_LIGHT = (219, 234, 254)   # table header bg
GRAY_800   = (30,  41,  59)
GRAY_600   = (71,  85, 105)
GRAY_100   = (241, 245, 249)
WHITE      = (255, 255, 255)
GREEN      = (22,  163,  74)


class QuotePDF(FPDF):
    def __init__(self, quote_id: int):
        super().__init__()
        self.quote_id = quote_id
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(20, 20, 20)

    # ── Header ────────────────────────────────────────────────────────────────
    def header(self):
        # Company name bar
        self.set_fill_color(*BLUE)
        self.rect(0, 0, 210, 22, style="F")
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*WHITE)
        self.set_xy(10, 5)
        self.cell(0, 12, COMPANY_NAME, align="L")

        # "ESTIMATE" label on the right
        self.set_font("Helvetica", "B", 11)
        self.set_xy(10, 5)
        self.cell(0, 12, "ESTIMATE", align="R")
        self.ln(18)

    # ── Footer ────────────────────────────────────────────────────────────────
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*GRAY_600)
        self.cell(0, 10, "Thank you for your business!", align="C")


def generate_quote_pdf(quote) -> bytes:
    """
    Accepts a Quote model instance (or a plain dict with the same keys).
    Returns PDF as bytes.
    """
    pdf = QuotePDF(quote_id=quote.id if hasattr(quote, "id") else quote.get("id", 0))
    pdf.add_page()

    # ── Meta block ────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*GRAY_600)
    pdf.cell(0, 6, f"Quote #: {quote.id if hasattr(quote, 'id') else quote.get('id', '')}", ln=True)
    pdf.cell(0, 6, f"Date: {date.today().strftime('%B %d, %Y')}", ln=True)
    pdf.ln(4)

    # ── Customer info ─────────────────────────────────────────────────────────
    customer_name  = quote.customer_name  if hasattr(quote, "customer_name")  else quote.get("customer_name", "")
    customer_email = quote.customer_email if hasattr(quote, "customer_email") else quote.get("customer_email", "")
    job_type       = quote.job_type       if hasattr(quote, "job_type")       else quote.get("job_type", "")

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*GRAY_800)
    pdf.cell(0, 7, "Bill To", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, customer_name, ln=True)
    if customer_email:
        pdf.cell(0, 6, customer_email, ln=True)
    if job_type:
        pdf.set_text_color(*GRAY_600)
        pdf.cell(0, 6, f"Job type: {job_type}", ln=True)
    pdf.ln(6)

    # ── Line items table ──────────────────────────────────────────────────────
    line_items = quote.line_items if hasattr(quote, "line_items") else quote.get("line_items", [])
    tax_rate   = quote.tax_rate   if hasattr(quote, "tax_rate")   else quote.get("tax_rate", 0.0)
    notes_text = quote.notes      if hasattr(quote, "notes")       else quote.get("notes", "")

    col_w = [90, 25, 35, 35]  # Description | Qty | Unit Price | Line Total
    headers = ["Description", "Qty", "Unit Price", "Total"]

    # Table header row
    pdf.set_fill_color(*BLUE_LIGHT)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*BLUE)
    for w, h in zip(col_w, headers):
        pdf.cell(w, 8, h, border=0, align="R" if h != "Description" else "L", fill=True)
    pdf.ln()

    # Data rows (alternating bg)
    subtotal = 0.0
    for idx, item in enumerate(line_items):
        desc       = str(item.get("desc", ""))
        qty        = float(item.get("qty", 1))
        unit_price = float(item.get("unit_price", 0))
        line_total = qty * unit_price
        subtotal  += line_total

        pdf.set_fill_color(*GRAY_100) if idx % 2 == 0 else pdf.set_fill_color(*WHITE)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*GRAY_800)

        pdf.cell(col_w[0], 7, desc,                           border=0, fill=True)
        pdf.cell(col_w[1], 7, str(int(qty) if qty == int(qty) else qty), border=0, align="R", fill=True)
        pdf.cell(col_w[2], 7, f"${unit_price:,.2f}",          border=0, align="R", fill=True)
        pdf.cell(col_w[3], 7, f"${line_total:,.2f}",          border=0, align="R", fill=True)
        pdf.ln()

    pdf.ln(3)

    # ── Totals block ──────────────────────────────────────────────────────────
    right_x  = 185  # right margin
    label_w  = 40
    value_w  = 35
    label_x  = right_x - label_w - value_w

    def totals_row(label, value, bold=False):
        pdf.set_x(label_x)
        pdf.set_font("Helvetica", "B" if bold else "", 9)
        pdf.set_text_color(*GRAY_800)
        pdf.cell(label_w, 7, label, align="L")
        pdf.cell(value_w, 7, value, align="R")
        pdf.ln()

    totals_row("Subtotal", f"${subtotal:,.2f}")

    tax_amount = 0.0
    if tax_rate and tax_rate > 0:
        tax_amount = subtotal * tax_rate
        totals_row(f"Tax ({tax_rate*100:.1f}%)", f"${tax_amount:,.2f}")

    grand_total = subtotal + tax_amount

    # Green total bar
    pdf.set_fill_color(*GREEN)
    pdf.set_x(label_x)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*WHITE)
    pdf.cell(label_w + value_w, 9, f"TOTAL   ${grand_total:,.2f}", align="R", fill=True)
    pdf.ln(12)

    # ── Notes ─────────────────────────────────────────────────────────────────
    if notes_text and notes_text.strip():
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*GRAY_800)
        pdf.cell(0, 6, "Notes", ln=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*GRAY_600)
        pdf.multi_cell(0, 5, notes_text.strip())

    return bytes(pdf.output())
