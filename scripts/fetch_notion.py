#!/usr/bin/env python3
"""
fetch_notion.py
----------------
Pipeline de integração Notion -> dados.json

Lê a base de dados de obras da SEINFRA/UFG a partir da API do Notion,
trata a paginação, normaliza os campos e grava o resultado em
`dados.json` na raiz do repositório, pronto para ser consumido pelo
dashboard estático (index.html / app.js).

Variáveis de ambiente esperadas:
    NOTION_TOKEN        -> Token de integração interna do Notion ("secret_...")
    NOTION_DATABASE_ID  -> ID da base de dados de obras no Notion

Uso:
    NOTION_TOKEN=xxx NOTION_DATABASE_ID=yyy python scripts/fetch_notion.py
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

NOTION_API_VERSION = "2022-06-28"
NOTION_API_URL = "https://api.notion.com/v1"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "dados.json"

# Nomes das propriedades esperadas na base do Notion.
# Ajuste aqui caso os nomes das colunas na sua base sejam diferentes.
PROP_NAMES = {
    "obra": ["Obra", "Portaria", "Nome", "Name"],
    "fiscais": ["Fiscais", "Fiscal", "Responsáveis", "Responsavel"],
    "recurso": ["Recurso", "Tipo de Recurso", "Categoria"],
    "status": ["Status", "Situação"],
    "valor_total": ["Valor do Contrato", "Valor Total", "Valor", "Valor (R$)"],
    "latitude": ["Latitude", "Lat"],
    "longitude": ["Longitude", "Long", "Lng"],
    "data_inicio": ["Início Obra", "Data Início", "Data Inicio", "Início"],
    "previsao_termino": ["Prazo Obra", "Previsão Término", "Previsao Termino", "Término Previsto", "Previsão de Término"],
}


def get_env_or_die(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"[ERRO] Variável de ambiente obrigatória não definida: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def notion_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


def query_all_pages(database_id: str, headers: Dict[str, str]) -> List[Dict[str, Any]]:
    """Percorre a paginação da API do Notion até obter 100% dos registros."""
    url = f"{NOTION_API_URL}/databases/{database_id}/query"
    all_results: List[Dict[str, Any]] = []
    payload: Dict[str, Any] = {"page_size": 100}
    has_more = True
    next_cursor: Optional[str] = None
    page_count = 0

    while has_more:
        if next_cursor:
            payload["start_cursor"] = next_cursor

        response = requests.post(url, headers=headers, json=payload, timeout=30)

        if response.status_code == 429:
            # Rate limit: respeita o header Retry-After e tenta novamente.
            retry_after = int(response.headers.get("Retry-After", "1"))
            print(f"[AVISO] Rate limit atingido. Aguardando {retry_after}s...")
            time.sleep(retry_after)
            continue

        response.raise_for_status()
        data = response.json()

        all_results.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")
        page_count += 1
        print(f"[INFO] Página {page_count} lida ({len(data.get('results', []))} registros).")

    print(f"[INFO] Total de registros lidos do Notion: {len(all_results)}")
    return all_results


def find_property(properties: Dict[str, Any], candidates: List[str]) -> Optional[Dict[str, Any]]:
    for name in candidates:
        if name in properties:
            return properties[name]
    return None


def extract_title(prop: Optional[Dict[str, Any]]) -> str:
    if not prop:
        return ""
    prop_type = prop.get("type")
    if prop_type == "rich_text":
        return extract_rich_text(prop)
    items = prop.get("title", [])
    return "".join(item.get("plain_text", "") for item in items).strip()


def extract_rich_text(prop: Optional[Dict[str, Any]]) -> str:
    if not prop:
        return ""
    items = prop.get("rich_text", [])
    return "".join(item.get("plain_text", "") for item in items).strip()


def extract_select(prop: Optional[Dict[str, Any]]) -> str:
    if not prop:
        return ""
    select = prop.get("select")
    if select:
        return select.get("name", "")
    return ""


def extract_status(prop: Optional[Dict[str, Any]]) -> str:
    """Notion possui um tipo de propriedade dedicado 'status', além de 'select'."""
    if not prop:
        return ""
    if prop.get("type") == "status" and prop.get("status"):
        return prop["status"].get("name", "")
    return extract_select(prop)


def extract_multi_select(prop: Optional[Dict[str, Any]]) -> List[str]:
    if not prop:
        return []
    items = prop.get("multi_select", [])
    return [item.get("name", "") for item in items if item.get("name")]


def extract_people(prop: Optional[Dict[str, Any]]) -> List[str]:
    if not prop:
        return []
    items = prop.get("people", [])
    names = []
    for person in items:
        name = person.get("name")
        if name:
            names.append(name)
    return names


def extract_fiscais(prop: Optional[Dict[str, Any]]) -> List[str]:
    """Aceita 'fiscais' cadastrados como people, multi_select ou texto separado por vírgula."""
    if not prop:
        return []
    prop_type = prop.get("type")
    if prop_type == "people":
        return extract_people(prop)
    if prop_type == "multi_select":
        return extract_multi_select(prop)
    if prop_type in ("rich_text", "title"):
        raw = extract_rich_text(prop) if prop_type == "rich_text" else extract_title(prop)
        return [name.strip() for name in raw.split(",") if name.strip()]
    return []


def extract_number(prop: Optional[Dict[str, Any]]) -> float:
    if not prop:
        return 0.0
    value = prop.get("number")
    return float(value) if value is not None else 0.0


def extract_date(prop: Optional[Dict[str, Any]], which: str = "start") -> Optional[str]:
    if not prop:
        return None
    date_obj = prop.get("date")
    if not date_obj:
        return None
    return date_obj.get(which)


def normalize_page(page: Dict[str, Any]) -> Dict[str, Any]:
    props = page.get("properties", {})

    obra_prop = find_property(props, PROP_NAMES["obra"])
    fiscais_prop = find_property(props, PROP_NAMES["fiscais"])
    recurso_prop = find_property(props, PROP_NAMES["recurso"])
    status_prop = find_property(props, PROP_NAMES["status"])
    valor_prop = find_property(props, PROP_NAMES["valor_total"])
    lat_prop = find_property(props, PROP_NAMES["latitude"])
    lon_prop = find_property(props, PROP_NAMES["longitude"])
    inicio_prop = find_property(props, PROP_NAMES["data_inicio"])
    termino_prop = find_property(props, PROP_NAMES["previsao_termino"])

    return {
        "id": page.get("id"),
        "obra": extract_title(obra_prop),
        "fiscais": extract_fiscais(fiscais_prop),
        "recurso": extract_select(recurso_prop),
        "status": extract_status(status_prop),
        "valor_total": extract_number(valor_prop),
        "latitude": extract_number(lat_prop),
        "longitude": extract_number(lon_prop),
        "data_inicio": extract_date(inicio_prop, "start"),
        "previsao_termino": extract_date(termino_prop, "start"),
    }


def main() -> None:
    token = get_env_or_die("NOTION_TOKEN")
    database_id = get_env_or_die("NOTION_DATABASE_ID")

    headers = notion_headers(token)
    raw_pages = query_all_pages(database_id, headers)

    obras = [normalize_page(page) for page in raw_pages]

    # Remove registros sem nome de obra (ex.: linhas em branco no Notion).
    obras = [obra for obra in obras if obra["obra"]]

    output = {
        "atualizado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_obras": len(obras),
        "obras": obras,
    }

    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OK] {len(obras)} obras exportadas para {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
