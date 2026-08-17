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
import re
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
    "fiscais": ["Fiscais", "Fiscal", "Responsáveis", "Responsavel", "Responsável", "Fiscal de Obra", "Fiscais de Obra", "Engenheiro Fiscal", "Engenheiro Responsável"],
    "recurso": ["Recurso", "Tipo de Recurso", "Categoria", "Fonte de Recurso"],
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


PAGE_TITLE_CACHE: Dict[str, str] = {}


def get_page_title(page_id: str, headers: Dict[str, str]) -> str:
    if page_id in PAGE_TITLE_CACHE:
        return PAGE_TITLE_CACHE[page_id]
    try:
        url = f"{NOTION_API_URL}/pages/{page_id}"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            props = data.get("properties", {})
            for prop_name, prop_val in props.items():
                if prop_val.get("type") == "title":
                    title_text = extract_title(prop_val)
                    if title_text:
                        PAGE_TITLE_CACHE[page_id] = title_text
                        return title_text
    except Exception as e:
        print(f"[AVISO] Erro ao buscar página relacionada {page_id}: {e}")
    return ""


def extract_relation(prop: Optional[Dict[str, Any]], headers: Dict[str, str]) -> List[str]:
    if not prop:
        return []
    relation_items = prop.get("relation", [])
    names = []
    for rel in relation_items:
        page_id = rel.get("id")
        if page_id:
            title = get_page_title(page_id, headers)
            if title:
                names.append(title)
    return names


def extract_rollup(prop: Optional[Dict[str, Any]], headers: Dict[str, str]) -> List[str]:
    if not prop:
        return []
    rollup = prop.get("rollup", {})
    rollup_type = rollup.get("type")
    if rollup_type == "array":
        array = rollup.get("array", [])
        results = []
        for item in array:
            results.extend(extract_fiscais(item, headers))
        return results
    return []


def extract_fiscais(prop: Optional[Dict[str, Any]], headers: Dict[str, str]) -> List[str]:
    """Aceita 'fiscais' cadastrados como people, multi_select, select, relation, rollup ou texto separado por vírgula."""
    if not prop:
        return []
    prop_type = prop.get("type")
    if prop_type == "people":
        return extract_people(prop)
    if prop_type == "multi_select":
        return extract_multi_select(prop)
    if prop_type == "select":
        val = extract_select(prop)
        return [val] if val else []
    if prop_type == "relation":
        return extract_relation(prop, headers)
    if prop_type == "rollup":
        return extract_rollup(prop, headers)
    if prop_type in ("rich_text", "title"):
        raw = extract_rich_text(prop) if prop_type == "rich_text" else extract_title(prop)
        parts = [p.strip() for p in raw.replace(";", ",").replace("/", ",").split(",") if p.strip()]
        return parts
    return []


def parse_single_coord(s: str) -> float:
    if not s:
        return 0.0
    s_upper = s.upper()
    negative = False
    if '-' in s:
        negative = True
    if 'S' in s_upper or 'W' in s_upper or 'O' in s_upper:
        negative = True
    elif 'N' in s_upper or 'E' in s_upper:
        negative = False

    if '°' in s or "'" in s or '"' in s:
        nums = re.findall(r'[-+]?\d*\.\d+|\d+', s)
        if nums:
            try:
                vals = [float(n) for n in nums]
                deg = vals[0] if len(vals) > 0 else 0.0
                min_val = vals[1] if len(vals) > 1 else 0.0
                sec_val = vals[2] if len(vals) > 2 else 0.0
                val = deg + (min_val / 60.0) + (sec_val / 3600.0)
                return -val if negative else val
            except Exception:
                pass

    clean = s.replace("R$", "").replace("°", "").replace("'", "").replace('"', "").strip()
    clean = re.sub(r'[A-Za-z]', '', clean).strip()
    
    if "," in clean and "." in clean:
        if clean.rfind(",") > clean.rfind("."):
            clean = clean.replace(".", "").replace(",", ".")
        else:
            clean = clean.replace(",", "")
    elif "," in clean:
        clean = clean.replace(",", ".")

    match = re.search(r'[-+]?\d*\.\d+|\d+', clean)
    if match:
        try:
            val = float(match.group(0))
            if negative and val > 0:
                val = -val
            return val
        except ValueError:
            pass
            
    return 0.0


def extract_coordinate(prop: Optional[Dict[str, Any]], is_longitude: bool = False) -> float:
    if not prop:
        return 0.0
    
    value = prop.get("number")
    if value is not None:
        return float(value)
        
    prop_type = prop.get("type")
    raw = ""
    if prop_type == "rich_text":
        raw = extract_rich_text(prop)
    elif prop_type == "title":
        raw = extract_title(prop)
    elif prop_type == "number":
        val = prop.get("number")
        if val is not None:
            return float(val)
            
    if not raw:
        return 0.0
        
    raw_str = raw.strip()
    
    if ";" in raw_str:
        parts = [p.strip() for p in raw_str.split(";") if p.strip()]
    elif "," in raw_str and (" " in raw_str or raw_str.count("-") >= 2 or raw_str.count(".") >= 2):
        parts = [p.strip() for p in raw_str.split(",") if p.strip()]
    else:
        parts = [raw_str]

    if len(parts) == 2:
        try:
            lat_candidate = parse_single_coord(parts[0])
            lon_candidate = parse_single_coord(parts[1])
            if lat_candidate != 0.0 or lon_candidate != 0.0:
                return lon_candidate if is_longitude else lat_candidate
        except Exception:
            pass

    return parse_single_coord(raw_str)


def extract_number(prop: Optional[Dict[str, Any]]) -> float:
    if not prop:
        return 0.0
    value = prop.get("number")
    if value is not None:
        return float(value)
    prop_type = prop.get("type")
    if prop_type in ("rich_text", "title"):
        raw = extract_rich_text(prop) if prop_type == "rich_text" else extract_title(prop)
        if not raw:
            return 0.0
        # Normaliza string numérica (ex: "R$ 1.234,56" ou "-16.6047")
        clean = raw.replace("R$", "").strip()
        if "," in clean and "." in clean:
            clean = clean.replace(".", "").replace(",", ".")
        elif "," in clean:
            clean = clean.replace(",", ".")
        try:
            return float(clean)
        except ValueError:
            pass
    return 0.0


def extract_date(prop: Optional[Dict[str, Any]], which: str = "start") -> Optional[str]:
    if not prop:
        return None
    date_obj = prop.get("date")
    if not date_obj:
        return None
    return date_obj.get(which)


def normalize_page(page: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
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
        "fiscais": extract_fiscais(fiscais_prop, headers),
        "recurso": extract_select(recurso_prop),
        "status": extract_status(status_prop),
        "valor_total": extract_number(valor_prop),
        "latitude": extract_coordinate(lat_prop, is_longitude=False),
        "longitude": extract_coordinate(lon_prop, is_longitude=True),
        "data_inicio": extract_date(inicio_prop, "start"),
        "previsao_termino": extract_date(termino_prop, "start"),
    }


def main() -> None:
    token = get_env_or_die("NOTION_TOKEN")
    database_id = get_env_or_die("NOTION_DATABASE_ID")

    headers = notion_headers(token)
    raw_pages = query_all_pages(database_id, headers)

    obras = [normalize_page(page, headers) for page in raw_pages]

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
