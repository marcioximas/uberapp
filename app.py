import os
from datetime import timedelta

import click
from flask import Flask, render_template
from flask_login import current_user
from dotenv import load_dotenv

from extensions import db, login_manager, csrf, migrate
from models import User, Car, Fine, GPSReading

load_dotenv()


def create_app(test_config=None):
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-troque-em-producao")
    database_url = os.environ.get("DATABASE_URL", "sqlite:///uberapp.db")
    # Render fornece URLs no formato postgres://, mas SQLAlchemy exige postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = os.environ.get(
        "UPLOAD_FOLDER", os.path.join(app.root_path, "uploads")
    )
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)

    from blueprints.auth import auth_bp
    from blueprints.dashboard import dashboard_bp
    from blueprints.cars import cars_bp
    from blueprints.drivers import drivers_bp
    from blueprints.agreements import agreements_bp
    from blueprints.financeiro import financeiro_bp
    from blueprints.gps import gps_bp
    from blueprints.maintenance import maintenance_bp
    from blueprints.fines import fines_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(cars_bp)
    app.register_blueprint(drivers_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(financeiro_bp)
    app.register_blueprint(gps_bp)
    app.register_blueprint(maintenance_bp)
    app.register_blueprint(fines_bp)

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    @app.template_filter("cpf_mascarado")
    def format_cpf_mascarado(document):
        """Mascara o CPF/CNPJ pra não deixar o documento exposto nas listagens
        e telas de detalhe — mostra só os 2 últimos dígitos."""
        if not document:
            return document
        digitos = "".join(ch for ch in document if ch.isdigit())
        if len(digitos) <= 2:
            return "*" * len(digitos)
        if len(digitos) == 11:
            return f"***.***.***-{digitos[-2:]}"
        if len(digitos) == 14:
            return f"**.***.***/****-{digitos[-2:]}"
        return "*" * (len(digitos) - 2) + digitos[-2:]

    @app.template_filter("km")
    def format_km(valor):
        """Formata KM no padrão brasileiro (milhar com ponto, decimal com
        vírgula), mostrando casas decimais só quando o valor não é inteiro —
        necessário desde que o relatório automático de GPS passou a gravar
        KM com frações (antes só existiam valores inteiros)."""
        if valor is None:
            return "-"
        valor = float(valor)
        texto = f"{valor:,.1f}" if valor % 1 else f"{int(valor):,}"
        return texto.replace(",", "X").replace(".", ",").replace("X", ".")

    @app.context_processor
    def inject_multas_pendentes_revisao():
        """Contagem de multas raspadas que ainda ninguém revisou — usada pelo
        alerta global (partials/_multas_alerta.html) em toda página logada,
        pra avisar assim que a automação diária encontra uma multa nova."""
        if not current_user.is_authenticated:
            return {"multas_pendentes_revisao_count": 0}
        count = Fine.query.filter_by(status="pending_review").count()
        return {"multas_pendentes_revisao_count": count}

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    @click.option("--name", default=None)
    def create_admin(username, password, name):
        """Cria o primeiro usuário administrador (dono/funcionário) do sistema."""
        if User.query.filter_by(username=username).first():
            click.echo(f"Usuário '{username}' já existe.")
            return
        user = User(username=username, name=name or username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Usuário '{username}' criado com sucesso.")

    @app.cli.command("backfill-gps-baseline")
    @click.option("--apply", is_flag=True, default=False,
                  help="Grava de fato; sem essa flag só mostra o que seria feito.")
    def backfill_gps_baseline(apply):
        """Correção pontual: para carros que ficaram com uma única leitura de
        GPS confirmada (sem nenhuma anterior pra comparar — ex.: primeira
        execução da automação diária antes dela passar a gravar a baseline
        sozinha), grava uma leitura baseline com KM 0 um dia antes, pra essa
        leitura já entrar no gráfico de KM por mês."""
        candidatos = []
        for carro in Car.query.filter_by(active=True).all():
            leituras = (
                GPSReading.query.filter(
                    GPSReading.car_id == carro.id, GPSReading.confirmed_km.isnot(None)
                )
                .order_by(GPSReading.reading_date, GPSReading.created_at)
                .all()
            )
            if len(leituras) == 1:
                candidatos.append((carro, leituras[0]))

        if not candidatos:
            click.echo("Nenhum carro com leitura solta (sem baseline) encontrado.")
            return

        for carro, leitura in candidatos:
            baseline_date = leitura.reading_date - timedelta(days=1) if leitura.reading_date else None
            click.echo(
                f"{carro.plate}: leitura única confirmed_km={leitura.confirmed_km} "
                f"em {leitura.reading_date} -> baseline confirmed_km=0 em {baseline_date}"
            )
            if apply:
                db.session.add(GPSReading(
                    car_id=carro.id,
                    image_filename=f"backfill-baseline:{carro.plate}",
                    confidence_note="Leitura baseline gravada manualmente via backfill (correção pontual).",
                    status="confirmed",
                    confirmed_km=0,
                    reading_date=baseline_date,
                ))

        if apply:
            db.session.commit()
            click.echo(f"{len(candidatos)} leitura(s) baseline gravada(s).")
        else:
            click.echo("Modo simulação (sem --apply, nada foi gravado). Rode de novo com --apply pra gravar.")

    return app


app = create_app()


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


if __name__ == "__main__":
    app.run(debug=True)
