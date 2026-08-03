import tempfile

import pytest
from sqlalchemy.pool import StaticPool

from app import create_app
from extensions import db as _db
from models import User


@pytest.fixture()
def app():
    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        },
        "WTF_CSRF_ENABLED": False,
        "UPLOAD_FOLDER": tempfile.mkdtemp(),
    }
    application = create_app(test_config)

    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_user(db):
    user = User(username="admin", name="Admin")
    user.set_password("teste1234")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def auth_client(client, admin_user):
    client.post(
        "/login",
        data={"username": "admin", "password": "teste1234"},
        follow_redirects=True,
    )
    return client
