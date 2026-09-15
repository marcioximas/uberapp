from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import (
    StringField,
    PasswordField,
    IntegerField,
    DecimalField,
    DateField,
    SelectField,
    TextAreaField,
    SubmitField,
)
from wtforms.validators import DataRequired, Optional, Length, NumberRange


class LoginForm(FlaskForm):
    username = StringField("Usuário", validators=[DataRequired()])
    password = PasswordField("Senha", validators=[DataRequired()])
    submit = SubmitField("Entrar")


class CarForm(FlaskForm):
    plate = StringField("Placa", validators=[DataRequired(), Length(max=20)])
    model = StringField("Modelo", validators=[Optional(), Length(max=120)])
    year = IntegerField("Ano", validators=[Optional()])
    renavam = StringField("RENAVAM", validators=[Optional(), Length(max=20)])
    chassi = StringField("Chassi", validators=[Optional(), Length(max=30)])
    submit = SubmitField("Salvar")


class DriverForm(FlaskForm):
    name = StringField("Nome", validators=[DataRequired(), Length(max=120)])
    phone = StringField("Telefone", validators=[Optional(), Length(max=30)])
    document = StringField("CPF", validators=[Optional(), Length(max=20)])
    submit = SubmitField("Salvar")


class RentalAgreementForm(FlaskForm):
    driver_id = SelectField("Motorista", coerce=int, validators=[DataRequired()])
    amount = DecimalField("Valor do aluguel (R$)", places=2, validators=[DataRequired()])
    frequency = SelectField(
        "Frequência",
        choices=[("weekly", "Semanal"), ("monthly", "Mensal")],
        validators=[DataRequired()],
    )
    weekday = SelectField(
        "Dia da semana (aluguel semanal)",
        choices=[
            ("0", "Segunda"),
            ("1", "Terça"),
            ("2", "Quarta"),
            ("3", "Quinta"),
            ("4", "Sexta"),
            ("5", "Sábado"),
            ("6", "Domingo"),
        ],
        validators=[Optional()],
    )
    day_of_month = IntegerField(
        "Dia do mês (aluguel mensal)", validators=[Optional(), NumberRange(min=1, max=28)]
    )
    start_date = DateField("Início da vigência", validators=[DataRequired()])
    reliability_pct = IntegerField(
        "Confiabilidade de pagamento (%)",
        default=100,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    notes = TextAreaField("Observações", validators=[Optional()])
    submit = SubmitField("Salvar contrato")


class CSVUploadForm(FlaskForm):
    file = FileField(
        "Extrato CSV (Itaú)",
        validators=[FileRequired(), FileAllowed(["csv"], "Envie um arquivo .csv")],
    )
    submit = SubmitField("Importar")


class ManualAssignForm(FlaskForm):
    # CSRF é desabilitado aqui e renderizado manualmente (sem prefixo) no template,
    # já que várias instâncias deste form (uma por transação) aparecem na mesma
    # página com prefix= — um campo csrf_token prefixado não bate com o nome
    # ("csrf_token") que a proteção CSRF global do Flask-WTF espera encontrar.
    class Meta:
        csrf = False

    expected_charge_id = SelectField("Cobrança esperada", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Vincular")


class GPSUploadForm(FlaskForm):
    car_id = SelectField("Carro", coerce=int, validators=[DataRequired()])
    image = FileField(
        "Print do GPS",
        validators=[FileRequired(), FileAllowed(["jpg", "jpeg", "png"], "Envie uma imagem")],
    )
    submit = SubmitField("Enviar")


class GPSTextReportForm(FlaskForm):
    texto = TextAreaField(
        "Relatório \"Informações gerais\" colado do rastreador",
        validators=[DataRequired()],
    )
    submit = SubmitField("Analisar relatório")


class GPSReviewForm(FlaskForm):
    reading_date = DateField("Data do resumo", validators=[Optional()])
    confirmed_km = IntegerField("KM rodado", validators=[DataRequired(), NumberRange(min=0)])
    confirmed_max_speed = IntegerField("Velocidade máxima (km/h)", validators=[Optional()])
    confirmed_moving_time_minutes = IntegerField(
        "Tempo em movimento (minutos)", validators=[Optional()]
    )
    submit = SubmitField("Confirmar")


class MaintenanceItemForm(FlaskForm):
    name = StringField("Item de manutenção", validators=[DataRequired(), Length(max=120)])
    km_interval = IntegerField("Intervalo (KM)", validators=[Optional(), NumberRange(min=1)])
    date_interval_days = IntegerField(
        "Intervalo (dias)", validators=[Optional(), NumberRange(min=1)]
    )
    notes = TextAreaField("Observações", validators=[Optional()])
    submit = SubmitField("Salvar")


class MaintenanceLogForm(FlaskForm):
    done_date = DateField("Data do serviço", validators=[DataRequired()])
    done_km = IntegerField("KM na data do serviço", validators=[DataRequired(), NumberRange(min=0)])
    cost = DecimalField("Custo (R$)", places=2, validators=[Optional()])
    notes = TextAreaField("Observações", validators=[Optional()])
    submit = SubmitField("Registrar serviço")


class RecurringItemForm(FlaskForm):
    name = StringField("Nome (ex: Prestação financiamento)", validators=[DataRequired(), Length(max=120)])
    amount = DecimalField("Valor (R$)", places=2, validators=[DataRequired()])
    type = SelectField(
        "Tipo", choices=[("expense", "Saída"), ("income", "Entrada")], validators=[DataRequired()]
    )
    frequency = SelectField(
        "Frequência",
        choices=[("weekly", "Semanal"), ("monthly", "Mensal")],
        validators=[DataRequired()],
    )
    weekday = SelectField(
        "Dia da semana (se semanal)",
        choices=[
            ("0", "Segunda"),
            ("1", "Terça"),
            ("2", "Quarta"),
            ("3", "Quinta"),
            ("4", "Sexta"),
            ("5", "Sábado"),
            ("6", "Domingo"),
        ],
        validators=[Optional()],
    )
    day_of_month = IntegerField(
        "Dia do mês (se mensal)", validators=[Optional(), NumberRange(min=1, max=28)]
    )
    start_date = DateField("Início da vigência", validators=[DataRequired()])
    installments = IntegerField(
        "Número de parcelas (deixe em branco se não tiver fim definido)",
        validators=[Optional(), NumberRange(min=1, max=600)],
    )
    notes = TextAreaField("Observações", validators=[Optional()])
    submit = SubmitField("Salvar")


class AdHocEntryForm(FlaskForm):
    car_id = SelectField("Carro", coerce=int, validators=[DataRequired()])
    type = SelectField(
        "Tipo", choices=[("expense", "Saída"), ("income", "Entrada")], validators=[DataRequired()]
    )
    description = StringField("Descrição", validators=[DataRequired(), Length(max=255)])
    amount = DecimalField("Valor (R$)", places=2, validators=[DataRequired()])
    entry_date = DateField("Data (1ª parcela)", validators=[DataRequired()])
    installments = IntegerField(
        "Número de parcelas",
        default=1,
        validators=[Optional(), NumberRange(min=1, max=600)],
    )
    submit = SubmitField("Lançar")


class FineReviewForm(FlaskForm):
    confirmed_valor = DecimalField("Valor (R$)", places=2, validators=[DataRequired()])
    confirmed_vencimento = DateField("Vencimento", validators=[Optional()])
    notes = TextAreaField("Observações", validators=[Optional()])
    submit = SubmitField("Confirmar")


class CashSettingsForm(FlaskForm):
    saldo_inicial = DecimalField("Saldo inicial (R$)", places=2, validators=[DataRequired()])
    saldo_data = DateField("Data de referência do saldo", validators=[DataRequired()])
    submit = SubmitField("Salvar")
