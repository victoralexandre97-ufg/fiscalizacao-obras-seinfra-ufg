# Painel de Obras — SEINFRA UFG

Dashboard de acompanhamento de obras da SEINFRA/UFG em formato **signage** (dark mode, tela cheia, sem rolagem), com sincronização automática de uma base de dados do **Notion** via **GitHub Actions**, publicado no **GitHub Pages**.

```
├── scripts/
│   └── fetch_notion.py        # Lê a base do Notion e gera dados.json
├── .github/workflows/
│   └── notion_sync.yml        # Agenda a sincronização e o deploy no Pages
├── index.html                 # Estrutura do dashboard
├── styles.css                 # Tema dark/neon (Inter + JetBrains Mono)
├── app.js                     # Filtros, KPIs, mapa (Leaflet) e gráficos (Chart.js)
└── dados.json                 # Dados consumidos pelo front-end (gerado/atualizado pelo pipeline)
```

---

## 1. Como estruturar a base no Notion

Crie (ou reaproveite) uma **base de dados (database)** no Notion com as colunas abaixo. Os nomes sugeridos já são reconhecidos automaticamente pelo script; se usar outros nomes, ajuste o dicionário `PROP_NAMES` em `scripts/fetch_notion.py`.

| Coluna no Notion         | Tipo recomendado           | Campo no `dados.json` |
|---------------------------|-----------------------------|------------------------|
| `Obra`                    | Título (title)               | `obra` |
| `Fiscais`                 | Pessoas ou Multi-select      | `fiscais` |
| `Recurso`                 | Select (`Próprio UFG`, `Terceirizado/PAC`, ...) | `recurso` |
| `Status`                  | Status ou Select (`Em Andamento`, `Concluída`, `Atrasada`, `Paralisada`) | `status` |
| `Valor Total`             | Número                       | `valor_total` |
| `Latitude`                | Número                       | `latitude` |
| `Longitude`               | Número                       | `longitude` |
| `Data Início`             | Data                          | `data_inicio` |
| `Previsão Término`        | Data                          | `previsao_termino` |

> Dica: use o Google Maps para obter latitude/longitude de cada obra (clique com o botão direito no local → copiar coordenadas).

---

## 2. Criar a integração (token) do Notion

1. Acesse [notion.so/my-integrations](https://www.notion.so/my-integrations).
2. Clique em **"+ New integration"**.
3. Dê um nome (ex.: `SEINFRA Dashboard`), selecione o workspace correto e crie.
4. Copie o **"Internal Integration Secret"** — esse é o valor de `NOTION_TOKEN` (começa com `secret_` ou `ntn_`).
5. Abra a base de dados de obras no Notion, clique em **"..."** (canto superior direito) → **"Conexões"** (Connections) → adicione a integração criada. Sem esse passo, a API retorna erro 403 mesmo com o token correto.

### Obter o `NOTION_DATABASE_ID`

1. Abra a base de dados no navegador (não dentro de uma página, mas como "Full page").
2. A URL terá o formato:
   ```
   https://www.notion.so/seu-workspace/NOME-DA-BASE-<DATABASE_ID>?v=...
   ```
3. O `DATABASE_ID` é o trecho de 32 caracteres (hexadecimal) logo antes do `?v=`. Exemplo:
   ```
   https://www.notion.so/seuworkspace/Obras-SEINFRA-1a2b3c4d5e6f7081a2b3c4d5e6f70812
   ```
   → `NOTION_DATABASE_ID = 1a2b3c4d5e6f7081a2b3c4d5e6f70812`

---

## 3. Cadastrar os Secrets no GitHub

1. No repositório, acesse **Settings → Secrets and variables → Actions**.
2. Clique em **"New repository secret"** e cadastre:
   - `NOTION_TOKEN` → o Internal Integration Secret copiado no passo anterior.
   - `NOTION_DATABASE_ID` → o ID da base de dados copiado da URL.
3. Salve. Os valores ficam criptografados e são injetados apenas em tempo de execução do workflow.

---

## 4. Ativar o GitHub Pages

1. Vá em **Settings → Pages**.
2. Em **"Build and deployment" → "Source"**, selecione **"GitHub Actions"**.
3. Não é necessário selecionar uma branch específica — o workflow `notion_sync.yml` já cuida do build/deploy.

---

## 5. Executando manualmente

- Vá até a aba **Actions** do repositório, selecione o workflow **"Sincronização Notion -> Dashboard SEINFRA"** e clique em **"Run workflow"** para forçar uma sincronização imediata.
- Por padrão, o workflow roda automaticamente **a cada 6 horas** (`0 */6 * * *`) e também a cada push na branch `main`.

---

## 6. Testando localmente antes de subir para o GitHub

```bash
# instalar dependência
pip install requests

# exportar as variáveis (substitua pelos seus valores)
export NOTION_TOKEN="secret_xxx"
export NOTION_DATABASE_ID="1a2b3c4d5e6f7081a2b3c4d5e6f70812"

# rodar o script
python scripts/fetch_notion.py

# servir o dashboard localmente
python -m http.server 8080
# abra http://localhost:8080
```

O repositório já vem com um `dados.json` de exemplo (dados fictícios) para que o dashboard funcione visualmente mesmo antes da primeira sincronização.

---

## 7. Personalizações rápidas

- **Cores de status/recurso**: ajuste as variáveis CSS em `styles.css` (`--status-*`, `--accent-*`) e os objetos `STATUS_META` / `RECURSO_CORES` em `app.js`.
- **Frequência de sincronização**: altere o `cron` em `.github/workflows/notion_sync.yml`.
- **Novos filtros/colunas**: adicione a extração da propriedade em `scripts/fetch_notion.py` e o campo correspondente no front-end (`index.html` / `app.js`).

---

## Licença

Uso interno — SEINFRA / Universidade Federal de Goiás.
