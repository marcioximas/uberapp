# H&M rent cars — Sistema de Gestão de Frota

## Módulos
1. **Financeiro** — Importação de extrato CSV do Itaú, conciliação por carro (aluguel fixo semanal/mensal por motorista), cobrança de parcelas atrasadas via WhatsApp
2. **Mês a mês & Projeção de caixa** — cada conta fixa (aluguel, prestação de financiamento, etc.) vira uma ocorrência mensal/semanal marcada manualmente como paga/recebida; lançamentos avulsos (conserto, multa); projeção de fluxo de caixa (6/12/24 meses) ponderada pela confiabilidade de pagamento de cada motorista, com alerta de saldo negativo; ranking de margem por carro no dashboard
3. **Manutenção & GPS** — Upload de prints do GPS, extração automática via IA, checklist de manutenção configurável por carro com alertas preventivos

## Stack
- Python + Flask (blueprints) + Flask-SQLAlchemy + Flask-Migrate
- PostgreSQL (produção) / SQLite (local)
- Flask-Login (autenticação simples) + Flask-WTF (formulários/CSRF)
- Bootstrap 5
- API Anthropic (visão computacional para leitura dos prints de GPS)
- WhatsApp Cloud API da Meta (cobrança de parcelas atrasadas)

## Instalação local

```bash
python -m venv .venv
.venv/Scripts/activate   # Windows (.venv/bin/activate no Linux/Mac)
pip install -r requirements.txt
cp .env.example .env     # edite com suas chaves
flask db upgrade
flask create-admin       # cria o primeiro usuário (dono/funcionário)
python app.py
# Acesse: http://localhost:5000
```

## Deploy no Render (gratuito)

### 1. Suba o código no GitHub
```bash
git add .
git commit -m "implementação inicial"
git push
```

### 2. Crie o banco PostgreSQL no Render
- Dashboard → New → PostgreSQL
- Nome: uberapp-db
- Plano: Free
- Copie a **Internal Database URL**

### 3. Crie o Web Service no Render
- New → Web Service → conecte o repositório
- Build command: `pip install -r requirements.txt && flask db upgrade`
- Start command: `gunicorn app:app`
- Plano: Free

### 4. Configure as variáveis de ambiente
No Web Service → Environment → Add todas as variáveis listadas abaixo.

### 5. Deploy
Clique em "Create Web Service".

### 6. Crie o primeiro usuário admin
No Render, abra um Shell do serviço (ou rode como um one-off job) e execute:
```bash
flask create-admin --username seu_usuario --password sua_senha
```
Sem esse passo o sistema não tem nenhum usuário e ninguém consegue logar.

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `SECRET_KEY` | Sim | Chave secreta do Flask (sessão/CSRF) |
| `DATABASE_URL` | Sim | URL do banco (Render fornece o do PostgreSQL; local usa SQLite por padrão) |
| `ANTHROPIC_API_KEY` | Sim (p/ módulo GPS) | Chave para leitura automática dos prints GPS |
| `WHATSAPP_TOKEN` | Não | Token da Meta Cloud API — cobrança automática de parcelas atrasadas |
| `WHATSAPP_PHONE_NUMBER_ID` | Não | ID do número de telefone comercial da Cloud API |
| `WHATSAPP_TEMPLATE_NAME` | Não | Nome do template aprovado (padrão: `cobranca_atraso`) |
| `WHATSAPP_TEMPLATE_LANG` | Não | Idioma do template (padrão: `pt_BR`) |

Sem as variáveis de WhatsApp configuradas, o botão "Enviar WhatsApp" na tela de conciliação continua visível mas mostra um erro amigável explicando que a integração não está configurada — o resto do sistema funciona normalmente.

## Como usar o mês a mês e a projeção de caixa
1. Cadastre as contas fixas de cada carro em Carro → **Nova conta fixa** (ex: prestação de financiamento) — nome livre, entrada ou saída, valor e frequência
2. Em Financeiro → **Mês a mês**, navegue pelos meses e marque cada aluguel/conta fixa como recebido/pago (o aluguel também pode ser confirmado manualmente ali, além da conciliação automática do extrato)
3. Lance gastos avulsos (conserto, multa, pneu) em Financeiro → **Mês a mês → Novo avulso** — eles aparecem no realizado do mês mas não entram na projeção, por serem imprevisíveis
4. Configure o saldo inicial em Financeiro → **Configurações**
5. Veja Financeiro → **Projeção de caixa** para os próximos 6/12/24 meses — soma o aluguel esperado (ponderado pela "confiabilidade de pagamento %" de cada motorista, configurável no contrato) e as contas fixas; avisa se o saldo projetado ficar negativo em algum mês

## Como usar o módulo GPS
1. Abra o app do rastreador no celular
2. Vá no resumo semanal do veículo
3. Tire print da tela
4. No sistema: Manutenção → Upload print GPS → selecione o carro → envie
5. A IA lê os dados automaticamente (KM, velocidade máx, tempo em movimento)
6. **Revise e confirme** os valores extraídos na tela de revisão (a IA pode errar — corrija se necessário antes de confirmar)
7. Só após a confirmação o hodômetro do carro é atualizado e os alertas de manutenção são recalculados

## Como configurar a cobrança via WhatsApp
A [Meta Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api) oficial **não permite enviar para grupos nem mencionar usuários** — apenas mensagens diretas (1 para 1) para um número de telefone.

1. Crie um app no [Meta for Developers](https://developers.facebook.com/) com o produto WhatsApp
2. Gere um token de acesso permanente e anote o `Phone Number ID`
3. Crie e aguarde a aprovação de um **Message Template** (Meta Business Manager) com 4 variáveis de corpo, na ordem: nome do motorista, placa do carro, valor, data de vencimento
4. Configure `WHATSAPP_TOKEN` e `WHATSAPP_PHONE_NUMBER_ID` (e o nome do template, se for diferente de `cobranca_atraso`)
5. Cadastre o telefone de cada motorista (com DDD) em Motoristas
6. Na tela de Conciliação, cobranças atrasadas/não pagas mostram um botão "Enviar WhatsApp"

## Testes

Três camadas de teste, em `tests/`:
- `tests/unit/` — lógica pura (geração de datas recorrentes, parsing de CSV, matching de conciliação, projeção de caixa, status de manutenção), sem precisar de servidor.
- `tests/api/` — rotas Flask via test client (`app.test_client()`), banco SQLite em memória por teste.
- `tests/e2e/` — Playwright dirigindo um Chromium de verdade contra o app rodando de fato (subprocess `flask run` + SQLite temporário), cobrindo login, cadastro de carro/motorista/contrato, mês a mês e avulsos.

```bash
pip install -r requirements-dev.txt
playwright install chromium   # só na primeira vez, baixa o navegador

pytest                        # roda tudo (unit + api + e2e)
pytest tests/unit tests/api   # só as camadas rápidas (sem navegador)
pytest tests/e2e              # só os testes de ponta a ponta
```

Os testes de unidade/API rodam com CSRF desabilitado (config de teste) para simplificar; os testes e2e passam pelo formulário real do navegador, então o CSRF funciona normalmente.

## Estrutura
```
uberapp/
├── app.py                # App factory Flask, registra blueprints, CLI create-admin
├── models.py              # Modelos SQLAlchemy
├── extensions.py           # db, login_manager, csrf, migrate
├── forms.py                 # Formulários WTForms
├── importador.py             # Importação CSV Itaú + lógica de conciliação
├── recorrencia.py              # Geração de datas de vencimento (semanal/mensal)
├── contas_fixas.py              # Geração de ocorrências de contas fixas por carro
├── projecao.py                   # Saldo atual + projeção de fluxo de caixa
├── gps_reader.py                  # Leitura de prints GPS via API Anthropic (visão)
├── whatsapp.py                     # Cobrança de parcelas atrasadas via Meta Cloud API
├── blueprints/                  # auth, dashboard, cars, drivers, agreements,
│                                  financeiro, gps, maintenance
├── migrations/                    # Flask-Migrate / Alembic
├── uploads/gps/                    # Screenshots enviados (disco local)
├── tests/                           # unit/, api/, e2e/ (ver seção Testes)
├── requirements.txt
├── requirements-dev.txt
└── templates/                       # HTML + Bootstrap
```

## Limitações conhecidas (v1)
- Imagens de GPS ficam em disco local; no plano gratuito do Render isso é efêmero entre deploys (os dados extraídos ficam salvos no banco normalmente, só o print em si pode se perder)
- Sem níveis de permissão — qualquer usuário logado acessa tudo
