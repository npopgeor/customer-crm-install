from datetime import datetime, timedelta

from extensions import db

partner_customer = db.Table(
    "partner_customer",
    db.Column("partner_id", db.Integer, db.ForeignKey("partner.id"), primary_key=True),
    db.Column(
        "customer_id", db.Integer, db.ForeignKey("customer.id"), primary_key=True
    ),
)

division_contacts = db.Table(
    "division_contacts",
    db.Column("division_id", db.Integer, db.ForeignKey("division.id")),
    db.Column("contact_id", db.Integer, db.ForeignKey("contact.id")),
)

customer_contacts = db.Table(
    "customer_contacts",
    db.Column("customer_id", db.Integer, db.ForeignKey("customer.id")),
    db.Column("contact_id", db.Integer, db.ForeignKey("contact.id")),
)

# Association Table (MUST be defined before usage)
division_contact = db.Table(
    "division_contact",
    db.Column(
        "division_id", db.Integer, db.ForeignKey("division.id"), primary_key=True
    ),
    db.Column("contact_id", db.Integer, db.ForeignKey("contact.id"), primary_key=True),
)

meeting_participants = db.Table(
    "meeting_participants",
    db.Column("meeting_id", db.Integer, db.ForeignKey("meeting.id")),
    db.Column("contact_id", db.Integer, db.ForeignKey("contact.id")),
)

opportunity_contacts = db.Table(
    'opportunity_contacts',
    db.Column('opportunity_id', db.Integer, db.ForeignKey('customer_opportunity.id')),
    db.Column('contact_id', db.Integer, db.ForeignKey('contact.id'))
)

# --------------------- MODELS ---------------------


class Contact(db.Model):
    __tablename__ = "contact"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100))
    phone = db.Column(db.String(50))
    role = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(100))
    reports_to = db.Column(db.Integer, db.ForeignKey("contact.id"))
    notes = db.Column(db.Text)
    contact_type = db.Column(db.String(20))
    technology = db.Column(db.String(100))  # New field added
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=True)
    partner_id = db.Column(db.Integer, db.ForeignKey("partner.id"), nullable=True)

    manager = db.relationship(
        "Contact", remote_side=[id], backref="subordinates", uselist=False
    )
    customer = db.relationship(
        "Customer", backref="contacts", foreign_keys=[customer_id]
    )
    partner = db.relationship("Partner", backref="contacts", foreign_keys=[partner_id])


class Partner(db.Model):
    __tablename__ = "partner"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    notes = db.Column(db.Text)

    customers = db.relationship(
        "Customer", secondary=partner_customer, backref="partners"
    )


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    cx_services = db.Column(db.Text)
    notes = db.Column(db.Text)

    divisions = db.relationship(
        "Division", back_populates="customer", cascade="all, delete-orphan"
    )
    action_items = db.relationship("ActionItem", backref="customer", lazy=True)
    meetings = db.relationship("Meeting", backref="customer", lazy=True)
    recurring_meetings = db.relationship(
        "RecurringMeeting", back_populates="customer", lazy=True
    )

    # New Relationships
    opportunities = db.relationship(
        "CustomerOpportunity",
        backref="customer",
        lazy=True,
        cascade="all, delete-orphan",
    )
    technologies = db.relationship(
        "CustomerTechnology",
        backref="customer",
        lazy=True,
        cascade="all, delete-orphan",
    )
    projects = db.relationship(
        "CustomerProject", backref="customer", lazy=True, cascade="all, delete-orphan"
    )

    def get_enriched_recurring_meetings(self):
        enriched = []
        today = datetime.now()
        for rm in self.recurring_meetings:
            next_time = rm.get_next_occurrence(today)
            recurrence = rm.get_human_readable_recurrence()
            enriched.append(
                {
                    "title": rm.title,
                    "recurrence": recurrence,
                    "next": (
                        next_time.strftime("%b %d, %Y @ %I:%M %p") if next_time else "—"
                    ),
                }
            )
        return enriched


class RecurringMeeting(db.Model):
    __tablename__ = "recurring_meeting"
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    start_datetime = db.Column(db.DateTime, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    host = db.Column(db.String(100))
    recurrence_pattern = db.Column(db.String(50))  # e.g., daily, weekly, biweekly
    repeat_until = db.Column(db.Date)
    description = db.Column(db.Text)
    generate_ics = db.Column(db.Boolean, default=False)
    duration_minutes = db.Column(db.Integer, default=60)  # ✅ Added duration field

    customer = db.relationship("Customer", back_populates="recurring_meetings")

    def get_next_occurrence(self, today=None):
        today = today or datetime.now()
        current = self.start_datetime

        if current >= today:
            return current

        while current.date() <= self.repeat_until:
            if self.recurrence_pattern == "daily":
                current += timedelta(days=1)
            elif self.recurrence_pattern == "weekly":
                current += timedelta(weeks=1)
            elif self.recurrence_pattern == "biweekly":
                current += timedelta(weeks=2)
            elif self.recurrence_pattern == "monthly":
                current += timedelta(weeks=4)  # ⬅️ NOW really means "every 4 weeks"
            else:
                break

            if current >= today:
                return current

        return None

    def get_human_readable_recurrence(self):
        dt = self.start_datetime
        weekday = dt.strftime("%A")
        time_str = dt.strftime("%I:%M %p").lstrip("0")

        if self.recurrence_pattern == "daily":
            return f"Repeats daily at {time_str}"
        elif self.recurrence_pattern == "weekly":
            return f"Repeats every {weekday} at {time_str}"
        elif self.recurrence_pattern == "biweekly":
            return f"Repeats every other {weekday} at {time_str}"
        elif self.recurrence_pattern == "monthly":
            return f"Repeats every 4 weeks on {weekday} at {time_str}"  # 👈 Updated description
        else:
            return f"Repeats: {self.recurrence_pattern} at {time_str}"


class Division(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"))
    parent_id = db.Column(db.Integer, db.ForeignKey("division.id"))
    document = db.Column(db.String(200))

    customer = db.relationship("Customer", back_populates="divisions")
    parent = db.relationship("Division", remote_side=[id], backref="children")
    contacts = db.relationship(
        "Contact", secondary=division_contact, backref="divisions"
    )
    opportunities = db.relationship(
        "DivisionOpportunity", backref="division", cascade="all, delete-orphan"
    )
    technologies = db.relationship(
        "DivisionTechnology", backref="division", cascade="all, delete-orphan"
    )
    projects = db.relationship(
        "DivisionProject", backref="division", cascade="all, delete-orphan"
    )


class DivisionDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    division_id = db.Column(db.Integer, db.ForeignKey("division.id"), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    division = db.relationship("Division", backref="documents")


class ActionItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20))
    detail = db.Column(db.Text, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=True)
    customer_contact = db.Column(db.String(100))
    cisco_contact = db.Column(db.String(100))
    completed = db.Column(db.Boolean, default=False)
    category = db.Column(db.String(50), default="daily")  # ← NEW LINE

    updates = db.relationship(
        "ActionItemUpdate",
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="desc(ActionItemUpdate.timestamp)",
    )


class Meeting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=True)
    date = db.Column(db.String(20))
    title = db.Column(db.String(200))
    host = db.Column(db.String(100))
    notes = db.Column(db.Text)
    participants = db.relationship(
        "Contact", secondary=meeting_participants, backref="meetings"
    )


class DivisionOpportunity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    division_id = db.Column(db.Integer, db.ForeignKey("division.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    value = db.Column(db.String(100))
    stage = db.Column(db.String(100))
    notes = db.Column(db.Text)


class DivisionTechnology(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    division_id = db.Column(db.Integer, db.ForeignKey("division.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    discount_level = db.Column(db.Integer)
    notes = db.Column(db.Text)


class DivisionProject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    division_id = db.Column(db.Integer, db.ForeignKey("division.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(100))
    owner = db.Column(db.String(100))
    notes = db.Column(db.Text)


class CustomerOpportunity(db.Model):
    __tablename__ = 'customer_opportunity'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)

    title = db.Column(db.String(200), nullable=False)
    stage = db.Column(db.String(100))
    value = db.Column(db.String(100))
    notes = db.Column(db.Text)
    next_steps = db.Column(db.Text)

    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contacts = db.relationship('Contact', secondary=opportunity_contacts, backref='opportunities')


class CustomerTechnology(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    discount_level = db.Column(db.Integer)
    notes = db.Column(db.Text)


class CustomerProject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(100))
    owner = db.Column(db.String(100))
    notes = db.Column(db.Text)


class ActionItemUpdate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action_item_id = db.Column(
        db.Integer, db.ForeignKey("action_item.id"), nullable=False
    )
    update_text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    parent = db.relationship("ActionItem", back_populates="updates")


class FileIndex(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    relative_path = db.Column(db.String(500), unique=True, nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    parent_folder = db.Column(db.String(300))
    last_indexed = db.Column(db.DateTime, default=datetime.utcnow)


class HeatmapCell(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    column_name = db.Column(
        db.String(128), nullable=False
    )  # e.g., "Security", "Wireless"
    color = db.Column(db.String(20), nullable=True)  # e.g., "red", "yellow", "green"
    text = db.Column(db.String(255), nullable=True)  # editable cell content

    __table_args__ = (
        db.UniqueConstraint("customer_id", "column_name", name="_customer_column_uc"),
    )
    
class Link(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    link_text = db.Column(db.Text, nullable=True)  # formerly 'notes'
    url = db.Column(db.String(512), nullable=False)
    others = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)