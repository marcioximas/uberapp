# Uber Ximas — Sistema de Gestão de Frota

## Módulos
1. **Financeiro** — Importação de extrato CSV do Itaú, conciliação por carro, controle de motoristas
2. **Manutenção & GPS** — Upload de prints do GPS, extração automática via IA, alertas de manutenção preventiva

## Stack
- Python + Flask
- PostgreSQL (produção) / SQLite (local)
- Bootstrap 5
- API Anthropic (visão para leitura dos prints GPS)

## Instalação local

```bash
pip install flask gunicorn
python app.py
# Acesse: http://localhost:5000
```

## Deploy no Render (gratuito)

### 1. Suba o código no GitHub
```bash
git init
git add .
git commit -m "primeiro commit"
git remote add origin https://github.com/SEU_USER/uberapp.git
git push -u origin main
```

### 2. Crie o banco PostgreSQL no Render
- Dashboard → New → PostgreSQL
- Nome: uberapp-db
- Plano: Free
- Copie a **Internal Database URL**

### 3. Crie o Web Service no Render
- New → Web Service → conecte o repositório
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Plano: Free

### 4. Configure as variáveis de ambiente
No Web Service → Environment → Add:
- `DATABASE_URL` → cole a Internal Database URL do passo 2
- `ANTHROPIC_API_KEY` → sua chave da API Anthropic (para leitura dos prints GPS)

### 5. Deploy
Clique em "Create Web Service" — pronto!

## Variáveis de ambiente necessárias

| Variável | Descrição |
|---|---|
| `DATABASE_URL` | URL do PostgreSQL (Render fornece) |
| `ANTHROPIC_API_KEY` | Chave para leitura automática dos prints GPS |

## Como usar o módulo GPS
1. Abra o app do rastreador no celular
2. Vá no resumo semanal do veículo
3. Tire print da tela
4. No sistema: Manutenção → Upload print GPS → selecione o carro → envie
5. A IA lê os dados automaticamente (KM, velocidade máx, tempo em movimento)
6. O sistema atualiza o hodômetro e verifica alertas de manutenção

## Estrutura
```
uberapp/
├── app.py           # Flask + todas as rotas
├── models.py        # Banco de dados (SQLite/PostgreSQL)
├── importador.py    # Importação CSV do Itaú
├── gps_reader.py    # Leitura de prints GPS via IA
├── requirements.txt
└── templates/       # HTML + Bootstrap
```
# uberapp
