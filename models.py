from datetime import datetime, date

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db

# Janelas de tolerância da conciliação financeira (em dias)
TOLERANCIA_DIAS = 5
CARENCIA_MISSING_DIAS = 30

# Limiar de "atenção" nos alertas de manutenção (fração do intervalo)
LIMIAR_ATENCAO = 0.9


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120))
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return self.active


class Car(db.Model):
    __tablename__ = "cars"

    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(20), unique=True, nullable=False)
    model = db.Column(db.String(120))
    year = db.Column(db.Integer)
    renavam = db.Column(db.String(20))
    chassi = db.Column(db.String(30))  # usado na consulta de débitos/multas do Detran-DF
    current_km = db.Column(db.Float, default=0, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    rental_agreements = db.relationship(
        "RentalAgreement", back_populates="car", order_by="RentalAgreement.start_date.desc()"
    )
    maintenance_items = db.relationship("MaintenanceItem", back_populates="car")
    gps_readings = db.relationship(
        "GPSReading", back_populates="car", order_by="GPSReading.created_at.desc()"
    )
    fines = db.relationship(
        "Fine", back_populates="car", order_by="Fine.extracted_vencimento.desc()"
    )

    @property
    def current_agreement(self):
        for agreement in self.rental_agreements:
            if agreement.active and agreement.end_date is None:
                return agreement
        return None

    def __repr__(self):
        return f"<Car {self.plate}>"


class Driver(db.Model):
    __tablename__ = "drivers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30))
    document = db.Column(db.String(20))
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    rental_agreements = db.relationship(
        "RentalAgreement", back_populates="driver", order_by="RentalAgreement.start_date.desc()"
    )

    def __repr__(self):
        return f"<Driver {self.name}>"


class RentalAgreement(db.Model):
    __tablename__ = "rental_agreements"

    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    discounted_amount = db.Column(db.Numeric(10, 2))
    # valor cobrado se o motorista pagar em dia/adiantado; usado como alternativa
    # válida ao conciliar automaticamente as transações do extrato
    frequency = db.Column(db.String(10), nullable=False)  # "weekly" | "monthly"
    weekday = db.Column(db.Integer)  # 0=Monday, para frequency == weekly
    day_of_month = db.Column(db.Integer)  # 1-28, para frequency == monthly
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text)
    reliability_pct = db.Column(db.Integer, default=100, nullable=False)
    # % usado só na projeção de caixa, para ponderar motoristas que atrasam
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    car = db.relationship("Car", back_populates="rental_agreements")
    driver = db.relationship("Driver", back_populates="rental_agreements")
    expected_charges = db.relationship(
        "ExpectedCharge", back_populates="agreement", order_by="ExpectedCharge.due_date"
    )

    def __repr__(self):
        return f"<RentalAgreement car={self.car_id} driver={self.driver_id} amount={self.amount}>"


class ExpectedCharge(db.Model):
    __tablename__ = "expected_charges"
    __table_args__ = (
        db.UniqueConstraint("rental_agreement_id", "due_date", name="uq_agreement_due_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    rental_agreement_id = db.Column(
        db.Integer, db.ForeignKey("rental_agreements.id"), nullable=False
    )
    due_date = db.Column(db.Date, nullable=False)
    amount_expected = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(15), nullable=False, default="pending")
    # "pending" | "matched" | "late" | "missing"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notified_at = db.Column(db.DateTime)
    notified_count = db.Column(db.Integer, default=0, nullable=False)
    manually_confirmed = db.Column(db.Boolean, default=False, nullable=False)
    confirmed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    confirmed_at = db.Column(db.DateTime)

    agreement = db.relationship("RentalAgreement", back_populates="expected_charges")
    transaction = db.relationship(
        "Transaction", back_populates="matched_expected_charge", uselist=False
    )
    confirmed_by = db.relationship("User")

    def recompute_status(self, today=None):
        """Atualiza o status com base na data de hoje, se ainda não estiver conciliado."""
        if self.transaction is not None or self.manually_confirmed:
            self.status = "matched"
            return
        today = today or date.today()
        dias_atraso = (today - self.due_date).days
        if dias_atraso > CARENCIA_MISSING_DIAS:
            self.status = "missing"
        elif dias_atraso > TOLERANCIA_DIAS:
            self.status = "late"
        else:
            self.status = "pending"

    def __repr__(self):
        return f"<ExpectedCharge agreement={self.rental_agreement_id} due={self.due_date} {self.status}>"


class ImportBatch(db.Model):
    __tablename__ = "import_batches"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255))
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    imported_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    row_count = db.Column(db.Integer, default=0)
    skipped_row_count = db.Column(db.Integer, default=0)

    transactions = db.relationship("Transaction", back_populates="import_batch")
    imported_by = db.relationship("User")

    def __repr__(self):
        return f"<ImportBatch {self.filename} ({self.row_count} linhas)>"


class Transaction(db.Model):
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"), nullable=False)
    transaction_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(500))
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    raw_row = db.Column(db.Text)
    status = db.Column(db.String(15), nullable=False, default="unmatched")
    # "unmatched" | "matched" | "ignored"
    matched_expected_charge_id = db.Column(db.Integer, db.ForeignKey("expected_charges.id"))
    matched_car_id = db.Column(db.Integer, db.ForeignKey("cars.id"))
    matched_by = db.Column(db.String(10))  # "auto" | "manual"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    import_batch = db.relationship("ImportBatch", back_populates="transactions")
    matched_expected_charge = db.relationship("ExpectedCharge", back_populates="transaction")
    matched_car = db.relationship("Car")

    def __repr__(self):
        return f"<Transaction {self.transaction_date} {self.amount} {self.status}>"


class MaintenanceItem(db.Model):
    __tablename__ = "maintenance_items"

    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    km_interval = db.Column(db.Integer)
    date_interval_days = db.Column(db.Integer)
    last_done_km = db.Column(db.Integer)
    last_done_date = db.Column(db.Date)
    active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    car = db.relationship("Car", back_populates="maintenance_items")
    logs = db.relationship(
        "MaintenanceLog", back_populates="item", order_by="MaintenanceLog.done_date.desc()"
    )

    def _status_km(self, current_km):
        if not self.km_interval:
            return None
        desde_ultimo = current_km - (self.last_done_km or 0)
        if desde_ultimo >= self.km_interval:
            return "atrasado"
        if desde_ultimo >= self.km_interval * LIMIAR_ATENCAO:
            return "atencao"
        return "ok"

    def _status_data(self, today=None):
        if not self.date_interval_days:
            return None
        today = today or date.today()
        referencia = self.last_done_date or self.created_at.date()
        dias_desde_ultimo = (today - referencia).days
        if dias_desde_ultimo >= self.date_interval_days:
            return "atrasado"
        if dias_desde_ultimo >= self.date_interval_days * LIMIAR_ATENCAO:
            return "atencao"
        return "ok"

    def status_alerta(self, current_km, today=None):
        """Retorna 'ok' | 'atencao' | 'atrasado', o pior entre os critérios configurados."""
        ordem = {"ok": 0, "atencao": 1, "atrasado": 2}
        candidatos = [
            s
            for s in (self._status_km(current_km), self._status_data(today))
            if s is not None
        ]
        if not candidatos:
            return "ok"
        return max(candidatos, key=lambda s: ordem[s])

    def __repr__(self):
        return f"<MaintenanceItem {self.name} car={self.car_id}>"


class MaintenanceLog(db.Model):
    __tablename__ = "maintenance_logs"

    id = db.Column(db.Integer, primary_key=True)
    maintenance_item_id = db.Column(
        db.Integer, db.ForeignKey("maintenance_items.id"), nullable=False
    )
    done_date = db.Column(db.Date, nullable=False)
    done_km = db.Column(db.Integer, nullable=False)
    cost = db.Column(db.Numeric(10, 2))
    notes = db.Column(db.Text)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    item = db.relationship("MaintenanceItem", back_populates="logs")
    created_by = db.relationship("User")

    def __repr__(self):
        return f"<MaintenanceLog item={self.maintenance_item_id} {self.done_date}>"


class GPSReading(db.Model):
    __tablename__ = "gps_readings"

    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    image_filename = db.Column(db.String(255), nullable=False)

    extracted_km = db.Column(db.Float)
    extracted_max_speed = db.Column(db.Integer)
    extracted_moving_time_minutes = db.Column(db.Integer)
    raw_ai_response = db.Column(db.Text)
    confidence_note = db.Column(db.Text)

    status = db.Column(db.String(15), nullable=False, default="pending_review")
    # "pending_review" | "confirmed" | "rejected"

    confirmed_km = db.Column(db.Float)
    confirmed_max_speed = db.Column(db.Integer)
    confirmed_moving_time_minutes = db.Column(db.Integer)
    reading_date = db.Column(db.Date)

    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    car = db.relationship("Car", back_populates="gps_readings")
    reviewed_by = db.relationship("User")

    def __repr__(self):
        return f"<GPSReading car={self.car_id} {self.status}>"


class Fine(db.Model):
    """Multa raspada da consulta de débitos do Detran-DF (ver detran_df.py).

    Segue o mesmo padrão de GPSReading: campos extracted_* guardam o dado
    bruto vindo da raspagem; confirmed_valor/confirmed_vencimento/notes são
    correções humanas que uma nova raspagem (upsert_fine, em fines.py) nunca
    sobrescreve, junto com status/notes/paid_date.
    """

    __tablename__ = "fines"
    __table_args__ = (
        db.UniqueConstraint("car_id", "numero_ait", name="uq_fine_car_ait"),
    )

    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    numero_ait = db.Column(db.String(30), nullable=False)  # nº do Auto de Infração — chave natural

    extracted_data_infracao = db.Column(db.Date)
    extracted_local = db.Column(db.String(255))
    extracted_descricao = db.Column(db.String(255))
    extracted_valor = db.Column(db.Numeric(10, 2))
    extracted_vencimento = db.Column(db.Date)
    extracted_pontos = db.Column(db.Integer)
    extracted_orgao_status = db.Column(db.String(60))  # texto cru do status no site do Detran
    raw_response = db.Column(db.Text)  # JSON bruto da consulta, para depuração
    consulted_at = db.Column(db.DateTime)  # quando essa raspagem específica ocorreu

    confirmed_valor = db.Column(db.Numeric(10, 2))
    confirmed_vencimento = db.Column(db.Date)
    notes = db.Column(db.Text)

    status = db.Column(db.String(15), nullable=False, default="pending_review")
    # "pending_review" | "confirmed" | "paga" | "recorrida" | "rejected"
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    paid_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    car = db.relationship("Car", back_populates="fines")
    reviewed_by = db.relationship("User")

    @property
    def valor(self):
        return self.confirmed_valor if self.confirmed_valor is not None else self.extracted_valor

    @property
    def vencimento(self):
        return self.confirmed_vencimento if self.confirmed_vencimento is not None else self.extracted_vencimento

    def status_display(self, today=None):
        """'vencida' se ainda não resolvida e o vencimento já passou; senão, o status bruto."""
        if self.status in ("pending_review", "confirmed"):
            today = today or date.today()
            if self.vencimento and self.vencimento < today:
                return "vencida"
        return self.status

    def __repr__(self):
        return f"<Fine {self.numero_ait} car={self.car_id} {self.status}>"


class RecurringItem(db.Model):
    """Custo ou receita fixa por carro (ex: prestação de financiamento, seguro, rastreador)."""

    __tablename__ = "recurring_items"

    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # "income" | "expense"
    frequency = db.Column(db.String(10), nullable=False)  # "weekly" | "monthly"
    weekday = db.Column(db.Integer)
    day_of_month = db.Column(db.Integer)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    car = db.relationship("Car", backref="recurring_items")
    occurrences = db.relationship(
        "RecurringOccurrence", back_populates="item", order_by="RecurringOccurrence.due_date"
    )

    def parcelas_restantes(self, today=None):
        """Quantas parcelas ainda faltam vencer (None se não houver data de término definida)."""
        if not self.end_date:
            return None
        today = today or date.today()
        if today > self.end_date:
            return 0
        from recorrencia import gerar_datas_vencimento

        inicio = max(self.start_date, today)
        return sum(
            1
            for _ in gerar_datas_vencimento(
                inicio, self.frequency, self.weekday, self.day_of_month, self.end_date
            )
        )

    def __repr__(self):
        return f"<RecurringItem {self.name} car={self.car_id} {self.type}>"


class RecurringOccurrence(db.Model):
    """Ocorrência mensal/semanal de um RecurringItem, marcada paga/recebida manualmente."""

    __tablename__ = "recurring_occurrences"
    __table_args__ = (
        db.UniqueConstraint("recurring_item_id", "due_date", name="uq_item_due_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    recurring_item_id = db.Column(db.Integer, db.ForeignKey("recurring_items.id"), nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(10), nullable=False, default="pending")  # "pending" | "paid"
    paid_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    item = db.relationship("RecurringItem", back_populates="occurrences")

    def __repr__(self):
        return f"<RecurringOccurrence item={self.recurring_item_id} due={self.due_date} {self.status}>"


class AdHocEntry(db.Model):
    """Lançamento avulso (não-fixo) por carro: conserto, pneu, guincho, multa, etc.

    Não entra na projeção de fluxo de caixa — só no realizado do mês.
    """

    __tablename__ = "ad_hoc_entries"

    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # "income" | "expense"
    description = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    entry_date = db.Column(db.Date, nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    car = db.relationship("Car", backref="ad_hoc_entries")
    created_by = db.relationship("User")

    def __repr__(self):
        return f"<AdHocEntry {self.description} {self.amount} {self.type}>"


class CashSettings(db.Model):
    """Configuração única (id=1) do saldo inicial de caixa, ponto de partida da projeção."""

    __tablename__ = "cash_settings"

    id = db.Column(db.Integer, primary_key=True)
    saldo_inicial = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    saldo_data = db.Column(db.Date, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get(cls):
        settings = cls.query.get(1)
        if settings is None:
            settings = cls(id=1, saldo_inicial=0, saldo_data=date.today())
            db.session.add(settings)
            db.session.commit()
        return settings
