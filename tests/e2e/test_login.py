import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_login_success_shows_dashboard(page, live_server):
    page.goto(f"{live_server}/login")
    page.fill("input[name='username']", "admin")
    page.fill("input[name='password']", "teste1234")
    page.click("input[type='submit']")

    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()


def test_login_wrong_password_shows_error(page, live_server):
    page.goto(f"{live_server}/login")
    page.fill("input[name='username']", "admin")
    page.fill("input[name='password']", "senha-errada")
    page.click("input[type='submit']")

    expect(page.get_by_text("Usuário ou senha inválidos")).to_be_visible()


def test_unauthenticated_redirects_to_login(page, live_server):
    page.goto(f"{live_server}/carros/")
    expect(page).to_have_url(f"{live_server}/login?next=%2Fcarros%2F")


def test_logout_redirects_to_login(page, live_server):
    page.goto(f"{live_server}/login")
    page.fill("input[name='username']", "admin")
    page.fill("input[name='password']", "teste1234")
    page.click("input[type='submit']")
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()

    page.click("a:has-text('Sair')")
    expect(page.locator("input[type='submit']")).to_be_visible()
