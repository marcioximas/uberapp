import uuid
from datetime import date

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_confirmar_conta_fixa_no_mes_a_mes(logged_in_page, live_server):
    page = logged_in_page
    placa = "E2E" + uuid.uuid4().hex[:4].upper()

    page.goto(f"{live_server}/carros/novo")
    page.fill("input[name='plate']", placa)
    page.click("input[type='submit']")

    page.goto(f"{live_server}/carros/")
    page.click(f"a:has-text('{placa}')")

    page.click("a:has-text('Nova conta fixa')")
    page.fill("input[name='name']", "Prestação financiamento")
    page.fill("input[name='amount']", "650.00")
    page.select_option("select[name='type']", value="expense")
    page.select_option("select[name='frequency']", value="monthly")
    hoje = date.today()
    page.fill("input[name='day_of_month']", str(min(hoje.day, 28)))
    page.fill("input[name='start_date']", hoje.strftime("%Y-%m-%d"))
    page.click("input[type='submit']")
    expect(page.get_by_text("Conta fixa cadastrada com sucesso")).to_be_visible()

    page.goto(f"{live_server}/financeiro/mes-a-mes")
    expect(page.get_by_text("Prestação financiamento")).to_be_visible()

    linha = page.locator("tr", has_text="Prestação financiamento")
    linha.get_by_role("button", name="Marcar pago").click()

    expect(page.get_by_text("Ocorrência confirmada")).to_be_visible()
    linha = page.locator("tr", has_text="Prestação financiamento")
    expect(linha.get_by_role("button", name="Marcar pendente")).to_be_visible()


def test_lancar_avulso_aparece_no_mes(logged_in_page, live_server):
    page = logged_in_page
    placa = "E2E" + uuid.uuid4().hex[:4].upper()

    page.goto(f"{live_server}/carros/novo")
    page.fill("input[name='plate']", placa)
    page.click("input[type='submit']")

    hoje = date.today()
    page.goto(f"{live_server}/financeiro/avulsos/novo")
    page.select_option("select[name='car_id']", label=placa)
    page.select_option("select[name='type']", value="expense")
    page.fill("input[name='description']", "Troca de pneu")
    page.fill("input[name='amount']", "300.00")
    page.fill("input[name='entry_date']", hoje.strftime("%Y-%m-%d"))
    page.click("input[type='submit']")

    expect(page.get_by_text("Lançamento avulso registrado")).to_be_visible()
    expect(page.get_by_text("Troca de pneu")).to_be_visible()
