from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
import json

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(100), nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    phone         = db.Column(db.String(20))
    password_hash = db.Column(db.String(255), nullable=False)
    role          = db.Column(db.String(20), nullable=False)  # admin, manager, clerk, typist
    color         = db.Column(db.String(7), default='#6366f1')
    is_ai         = db.Column(db.Boolean, default=False, nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id':         self.id,
            'name':       self.name,
            'email':      self.email,
            'phone':      self.phone,
            'role':       self.role,
            'color':      self.color,
            'is_ai':      self.is_ai,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Client(db.Model):
    __tablename__ = 'clients'

    id                    = db.Column(db.Integer, primary_key=True)
    name                  = db.Column(db.String(100), nullable=False)
    email                 = db.Column(db.String(120), nullable=False)
    phone                 = db.Column(db.String(20))
    company               = db.Column(db.String(100))
    address               = db.Column(db.Text)
    logo                  = db.Column(db.Text)   # base64 encoded
    primary_color         = db.Column(db.String(7), default='#1E3A8A')
    report_disclaimer     = db.Column(db.Text)
    report_color_override = db.Column(db.String(7))
    report_photo_settings = db.Column(db.Text)             # JSON: photo placement prefs
    created_at            = db.Column(db.DateTime, default=datetime.utcnow)

    properties = db.relationship('Property', backref='client', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id':                    self.id,
            'name':                  self.name,
            'email':                 self.email,
            'phone':                 self.phone,
            'company':               self.company,
            'address':               self.address,
            'logo':                  self.logo,
            'primary_color':         self.primary_color,
            'report_disclaimer':     self.report_disclaimer,
            'report_color_override':  self.report_color_override,
            'report_photo_settings':  self.report_photo_settings,
            'created_at':             self.created_at.isoformat() if self.created_at else None,
        }


class Property(db.Model):
    __tablename__ = 'properties'

    id             = db.Column(db.Integer, primary_key=True)
    client_id      = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    address        = db.Column(db.Text, nullable=False)
    property_type  = db.Column(db.String(50))
    bedrooms       = db.Column(db.Integer)
    bathrooms      = db.Column(db.Integer)
    furnished      = db.Column(db.Boolean, default=False)
    parking        = db.Column(db.Boolean, default=False)
    garden         = db.Column(db.Boolean, default=False)
    notes          = db.Column(db.Text)
    overview_photo = db.Column(db.Text)  # base64 encoded
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    inspections = db.relationship('Inspection', backref='property', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id':             self.id,
            'client_id':      self.client_id,
            'client_name':    self.client.name if self.client else None,
            'address':        self.address,
            'property_type':  self.property_type,
            'bedrooms':       self.bedrooms,
            'bathrooms':      self.bathrooms,
            'furnished':      self.furnished,
            'parking':        self.parking,
            'garden':         self.garden,
            'notes':          self.notes,
            'overview_photo': self.overview_photo,
            'created_at':     self.created_at.isoformat() if self.created_at else None,
        }


class Inspection(db.Model):
    __tablename__ = 'inspections'

    id                      = db.Column(db.Integer, primary_key=True)
    property_id             = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=False)
    inspection_type         = db.Column(db.String(50), nullable=False)
    status                  = db.Column(db.String(20), default='created')
    source_inspection_id    = db.Column(db.Integer, db.ForeignKey('inspections.id'), nullable=True)

    inspector_id            = db.Column(db.Integer, db.ForeignKey('users.id'))
    typist_id               = db.Column(db.Integer, db.ForeignKey('users.id'))
    template_id             = db.Column(db.Integer, db.ForeignKey('templates.id'))

    tenant_email            = db.Column(db.String(255))
    client_email_override   = db.Column(db.String(255))
    conduct_date            = db.Column(db.DateTime)
    conduct_time_preference = db.Column(db.String(50))
    scheduled_date          = db.Column(db.DateTime)
    key_location            = db.Column(db.String(255))
    key_return              = db.Column(db.String(255))
    internal_notes          = db.Column(db.Text)

    notes       = db.Column(db.Text)
    report_data = db.Column(db.Text)  # JSON
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    inspector = db.relationship('User', foreign_keys=[inspector_id], backref='inspections_as_inspector')
    typist    = db.relationship('User', foreign_keys=[typist_id],    backref='inspections_as_typist')
    template  = db.relationship('Template', foreign_keys=[template_id])

    def to_dict(self):
        return {
            'id':                      self.id,
            'property_id':             self.property_id,
            'property_address':        self.property.address if self.property else None,
            'client_id':               self.property.client_id if self.property else None,
            'client_name':             self.property.client.name if self.property and self.property.client else None,
            'inspection_type':         self.inspection_type,
            'status':                  self.status,
            'source_inspection_id':    self.source_inspection_id,
            'inspector_id':            self.inspector_id,
            'inspector_name':          self.inspector.name if self.inspector else None,
            'typist_id':               self.typist_id,
            'typist_name':             self.typist.name if self.typist else None,
            'typist_is_ai':            self.typist.is_ai if self.typist else False,
            'template_id':             self.template_id,
            'tenant_email':            self.tenant_email,
            'client_email_override':   self.client_email_override,
            'conduct_date':            self.conduct_date.isoformat() if self.conduct_date else None,
            'conduct_time_preference': self.conduct_time_preference,
            'scheduled_date':          self.scheduled_date.isoformat() if self.scheduled_date else None,
            'key_location':            self.key_location,
            'key_return':              self.key_return,
            'internal_notes':          self.internal_notes,
            'notes':                   self.notes,
            'report_data':             self.report_data,
            'created_at':              self.created_at.isoformat() if self.created_at else None,
            'updated_at':              self.updated_at.isoformat() if self.updated_at else None,
        }


class Template(db.Model):
    __tablename__ = 'templates'

    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(100), nullable=False)
    inspection_type = db.Column(db.String(50), nullable=False)
    content         = db.Column(db.Text, nullable=False, default='{}')  # legacy JSON fallback
    is_default      = db.Column(db.Boolean, default=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sections = db.relationship(
        'Section', backref='template', lazy=True,
        cascade='all, delete-orphan',
        order_by='Section.order_index'
    )

    def to_dict(self):
        return {
            'id':              self.id,
            'name':            self.name,
            'inspection_type': self.inspection_type,
            'content':         self.content,
            'is_default':      self.is_default,
            'sections':        [s.to_dict() for s in self.sections],
            'created_at':      self.created_at.isoformat() if self.created_at else None,
            'updated_at':      self.updated_at.isoformat() if self.updated_at else None,
        }


class Section(db.Model):
    __tablename__ = 'sections'

    id           = db.Column(db.Integer, primary_key=True)
    template_id  = db.Column(db.Integer, db.ForeignKey('templates.id'), nullable=False)
    name         = db.Column(db.String(200), nullable=False)
    section_type = db.Column(db.String(50), default='room')   # 'room' | 'fixed'
    order_index  = db.Column(db.Integer, default=0)
    is_required  = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship(
        'Item', backref='section', lazy=True,
        cascade='all, delete-orphan',
        order_by='Item.order_index'
    )

    def to_dict(self):
        return {
            'id':           self.id,
            'template_id':  self.template_id,
            'name':         self.name,
            'section_type': self.section_type,
            'order_index':  self.order_index,
            'is_required':  self.is_required,
            'items':        [i.to_dict() for i in self.items],
        }


class Item(db.Model):
    __tablename__ = 'items'

    id                 = db.Column(db.Integer, primary_key=True)
    section_id         = db.Column(db.Integer, db.ForeignKey('sections.id'), nullable=False)
    name               = db.Column(db.String(200), nullable=False)
    description        = db.Column(db.Text, default='')
    requires_photo     = db.Column(db.Boolean, default=True)
    requires_condition = db.Column(db.Boolean, default=True)
    order_index        = db.Column(db.Integer, default=0)
    created_at         = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':                 self.id,
            'section_id':         self.section_id,
            'name':               self.name,
            'description':        self.description,
            'requires_photo':     self.requires_photo,
            'requires_condition': self.requires_condition,
            'order_index':        self.order_index,
        }


class SectionPreset(db.Model):
    """
    A saved section snapshot — stores the section name, category, and a JSON
    array of its items. Reusable building block when composing templates.
    """
    __tablename__ = 'section_presets'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    category    = db.Column(db.String(50), default='room')  # 'room' | 'fixed'
    items_json  = db.Column(db.Text, default='[]')          # JSON snapshot of items
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        items = json.loads(self.items_json) if self.items_json else []
        return {
            'id':          self.id,
            'name':        self.name,
            'description': self.description,
            'category':    self.category,
            'items':       items,
            'item_count':  len(items),
            'created_at':  self.created_at.isoformat() if self.created_at else None,
        }


class TranscriptionUsage(db.Model):
    __tablename__ = 'transcription_usage'

    id            = db.Column(db.Integer, primary_key=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    call_type     = db.Column(db.String(20), nullable=False)  # 'item' | 'full'
    inspection_id = db.Column(db.Integer, db.ForeignKey('inspections.id', ondelete='SET NULL'), nullable=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    audio_seconds = db.Column(db.Float, default=0)
    input_tokens  = db.Column(db.Integer, default=0)
    output_tokens = db.Column(db.Integer, default=0)
    section_type  = db.Column(db.String(30), default='room')

    def to_dict(self):
        USD_TO_GBP           = 0.79
        WHISPER_PER_MIN_USD  = 0.006
        HAIKU_IN_PER_1M_USD  = 0.80
        HAIKU_OUT_PER_1M_USD = 4.00

        whisper_usd = (self.audio_seconds / 60) * WHISPER_PER_MIN_USD
        claude_usd  = (self.input_tokens  / 1_000_000) * HAIKU_IN_PER_1M_USD + \
                      (self.output_tokens / 1_000_000) * HAIKU_OUT_PER_1M_USD
        total_gbp   = (whisper_usd + claude_usd) * USD_TO_GBP

        return {
            'id':            self.id,
            'created_at':    self.created_at.isoformat() if self.created_at else None,
            'call_type':     self.call_type,
            'inspection_id': self.inspection_id,
            'audio_seconds': self.audio_seconds,
            'input_tokens':  self.input_tokens,
            'output_tokens': self.output_tokens,
            'section_type':  self.section_type,
            'cost_gbp':      round(total_gbp, 4),
        }


class SystemSetting(db.Model):
    __tablename__ = 'system_settings'

    id    = db.Column(db.Integer, primary_key=True)
    key   = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
