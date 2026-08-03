import os

import click
from flask import Flask, render_template
from dotenv import load_dotenv

from extensions import db, login_manager, csrf, migrate
from models import User

load_dotenv()


def create_app():
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

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(cars_bp)
    app.register_blueprint(drivers_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(financeiro_bp)
    app.register_blueprint(gps_bp)
    app.register_blueprint(maintenance_bp)

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

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

    return app


app = create_app()


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


if __name__ == "__main__":
    app.run(debug=True)
