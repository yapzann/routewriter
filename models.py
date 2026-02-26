from datetime import date, datetime, timedelta
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Customer(db.Model):
    __tablename__ = "customers"

    id                = db.Column(db.Integer, primary_key=True)
    name              = db.Column(db.String(200), nullable=False)
    email             = db.Column(db.String(200))
    phone             = db.Column(db.String(50))
    address           = db.Column(db.Text)
    last_service_date = db.Column(db.Date)
    notes             = db.Column(db.Text)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    def is_due(self):
        """Return True if the customer is due for service (≥ 11 months since last service, or never serviced)."""
        if not self.last_service_date:
            return True
        return date.today() >= self.last_service_date + timedelta(days=335)

    def to_dict(self):
        return {
            "id":                self.id,
            "name":              self.name,
            "email":             self.email or "",
            "phone":             self.phone or "",
            "address":           self.address or "",
            "last_service_date": self.last_service_date.isoformat() if self.last_service_date else None,
            "notes":             self.notes or "",
            "is_due":            self.is_due(),
            "created_at":        self.created_at.isoformat(),
        }


class Quote(db.Model):
    __tablename__ = "quotes"

    id             = db.Column(db.Integer, primary_key=True)
    customer_name  = db.Column(db.String(200), nullable=False)
    customer_email = db.Column(db.String(200))
    job_type       = db.Column(db.String(200))
    line_items     = db.Column(db.JSON, nullable=False)   # [{desc, qty, unit_price}]
    tax_rate       = db.Column(db.Float, default=0.0)     # e.g. 0.08 for 8 %
    subtotal       = db.Column(db.Float)
    total          = db.Column(db.Float)
    notes          = db.Column(db.Text)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":             self.id,
            "customer_name":  self.customer_name,
            "customer_email": self.customer_email or "",
            "job_type":       self.job_type or "",
            "line_items":     self.line_items,
            "tax_rate":       self.tax_rate,
            "subtotal":       self.subtotal,
            "total":          self.total,
            "notes":          self.notes or "",
            "created_at":     self.created_at.isoformat(),
        }
