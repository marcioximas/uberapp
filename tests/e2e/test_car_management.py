import uuid

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def _placa_unica():
    return "E2E" + uuid.uuid4().hex[:4].upper()


def test_create_car_driver_and_agreement_flow(logged_in_page, live_server):
    page = logged_in_page
    placa = _placa_unica()

    # cria carro
    page.goto(f"{live_server}/carros/novo")
    page.fill("input[name='plate']", placa)
    page.fill("input[name='model']", "Onix")
    page.fill("input[name='year']", "2022")
    page.click("input[type='submit']")
    expect(page.get_by_text("Carro cadastrado com sucesso")).to_be_visible()
    expect(page.get_by_text(placa)).to_be_visible()

    # cria motorista
    nome_motorista = "Motorista " + uuid.uuid4().hex[:6]
    page.goto(f"{live_server}/motoristas/novo")
    page.fill("input[name='name']", nome_motorista)
    page.fill("input[name='phone']", "5511999998888")
    page.click("input[type='submit']")
    expect(page.get_by_text("Motorista cadastrado com sucesso")).to_be_visible()

    # abre o carro recém-criado
    page.goto(f"{live_server}/carros/")
    page.click(f"a:has-text('{placa}')")
    expect(page.get_by_role("heading", name=placa)).to_be_visible()

    # cria contrato de aluguel
    page.click("a:has-text('Criar contrato')")
    page.select_option("select[name='driver_id']", label=nome_motorista)
    page.fill("input[name='amount']", "400.00")
    page.select_option("select[name='frequency']", value="weekly")
    page.select_option("select[name='weekday']", value="0")
    page.fill("input[name='start_date']", "2026-07-01")
    page.click("input[type='submit']")

    expect(page.get_by_text("Contrato de aluguel criado com sucesso")).to_be_visible()
    expect(page.get_by_text(nome_motorista)).to_be_visible()
    expect(page.get_by_text("R$ 400.00")).to_be_visible()


def test_deactivate_car(logged_in_page, live_server):
    page = logged_in_page
    placa = _placa_unica()

    page.goto(f"{live_server}/carros/novo")
    page.fill("input[name='plate']", placa)
    page.click("input[type='submit']")
    expect(page.get_by_text(placa)).to_be_visible()

    page.once("dialog", lambda dialog: dialog.accept())
    row = page.locator("tr", has_text=placa)
    row.get_by_role("button", name="Desativar").click()

    expect(page.get_by_text(f"Carro {placa} desativado")).to_be_visible()
    row = page.locator("tr", has_text=placa)
    expect(row.get_by_text("Inativo")).to_be_visible()
