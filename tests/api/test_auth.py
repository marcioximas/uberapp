from models import User


def test_protected_route_redirects_to_login_when_not_authenticated(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_success(client, admin_user):
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "teste1234"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Dashboard".encode() in resp.data


def test_login_wrong_password(client, admin_user):
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "senha-errada"},
        follow_redirects=True,
    )
    assert "Usuário ou senha inválidos".encode() in resp.data


def test_login_inactive_user_is_rejected(client, db):
    user = User(username="inativo", name="Inativo", active=False)
    user.set_password("teste1234")
    db.session.add(user)
    db.session.commit()

    resp = client.post(
        "/login",
        data={"username": "inativo", "password": "teste1234"},
        follow_redirects=True,
    )
    assert "Usuário ou senha inválidos".encode() in resp.data


def test_logout_then_protected_route_redirects_again(auth_client):
    auth_client.get("/logout")
    resp = auth_client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
