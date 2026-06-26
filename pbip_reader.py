"""pbip_reader.py — Leitor nativo de projetos Power BI Project (.pbip).

Faz o parsing do modelo semântico em TMDL (`*.SemanticModel/definition/`) e do
relatório em PBIR (`*.Report/definition/`) e devolve os mesmos conjuntos de
registros que o ``backend.analyze_pbix`` deriva de um ``.pbix`` binário via
pbixray. Assim a montagem de grafo e a documentação existentes consomem um
``.pbip`` sem qualquer alteração adicional.

Motivação: arquivos salvos em formato ``.pbip`` guardam o modelo em TMDL (texto
versionável) e o relatório em PBIR, separados do ``.pbix``. O pbixray lê apenas
o binário ``.pbix`` e, nesse cenário, não enxerga páginas/visuais (ficam fora do
binário). Este módulo lê a fonte da verdade versionada, independente do ``.pbix``.

O formato TMDL é texto indentado por TABs. A estratégia é montar uma árvore por
indentação e interpretar os blocos ``table``/``column``/``measure``/``partition``
e ``relationship``/``expression``.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ─── Árvore por indentação (TABs) ─────────────────────────────────────────────


def _indent_of(line: str) -> int:
    """Conta o número de TABs iniciais (a indentação estrutural do TMDL)."""
    count = 0
    for char in line:
        if char == "\t":
            count += 1
        else:
            break
    return count


def _build_tree(text: str) -> dict[str, Any]:
    """Monta uma árvore de nós a partir do texto TMDL, agrupando por indentação.

    Cada nó: ``{"indent": int, "text": str, "raw": str, "children": list}``.
    Linhas em branco são ignoradas (não têm papel estrutural).
    """
    root: dict[str, Any] = {"indent": -1, "text": "", "raw": "", "children": []}
    stack: list[dict[str, Any]] = [root]
    for raw in text.splitlines():
        if not raw.strip():
            continue
        indent = _indent_of(raw)
        node = {"indent": indent, "text": raw.strip(), "raw": raw, "children": []}
        while stack[-1]["indent"] >= indent:
            stack.pop()
        stack[-1]["children"].append(node)
        stack.append(node)
    return root


_PROP_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*:")


def _is_property_line(text: str) -> bool:
    """Heurística: linha de propriedade TMDL (``key: value`` ou ``annotation ...``).

    As expressões DAX/M não começam com ``palavra:``; usam ``=``, colchetes,
    funções. Portanto este filtro separa propriedades (formatString, lineageTag,
    displayFolder, mode, annotation, dataType, sourceColumn...) do corpo da
    expressão sem descartar linhas de código.
    """
    return bool(_PROP_RE.match(text)) or text.startswith("annotation ")


def _dedent(text: str) -> str:
    """Remove o número mínimo de TABs iniciais comum a todas as linhas não vazias."""
    lines = text.split("\n")
    indents = [_indent_of(line) for line in lines if line.strip()]
    base = min(indents) if indents else 0
    return "\n".join(line[base:] if line.strip() else "" for line in lines).strip("\n")


def _value_after_eq(node: dict[str, Any]) -> str:
    """Extrai o valor de um nó ``key = ...`` (medida, coluna calculada, source).

    Se houver conteúdo após o ``=`` na própria linha, é uma expressão inline.
    Caso contrário, o valor é o bloco de linhas filhas (mais indentadas),
    excluindo subárvores de propriedades.
    """
    text = node["text"]
    eq_index = text.find("=")
    if eq_index != -1:
        inline = text[eq_index + 1:].strip()
        if inline:
            return inline

    parts: list[str] = []

    def walk(current: dict[str, Any]) -> None:
        for child in current["children"]:
            if _is_property_line(child["text"]):
                continue  # ignora a subárvore inteira da propriedade
            parts.append(child["raw"])
            walk(child)

    walk(node)
    return _dedent("\n".join(parts))


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def _decl_name(text: str, keyword: str) -> str:
    """Nome de uma declaração TMDL (``table X``, ``measure 'X' = ...``)."""
    rest = text[len(keyword):].strip()
    eq_index = rest.find("=")
    name_part = rest[:eq_index] if eq_index != -1 else rest
    return _unquote(name_part)


def _child_props(node: dict[str, Any]) -> dict[str, str]:
    """Coleta propriedades ``key: value`` (e flags como ``isHidden``) dos filhos diretos."""
    props: dict[str, str] = {}
    for child in node["children"]:
        match = re.match(r"^([A-Za-z]+)\s*:\s*(.*)$", child["text"])
        if match:
            props[match.group(1)] = match.group(2).strip()
        elif child["text"] == "isHidden":
            props["isHidden"] = "true"
    return props


def _split_ref(ref: str) -> tuple[str, str]:
    """Separa ``Tabela.Coluna`` em (tabela, coluna), respeitando aspas simples."""
    ref = ref.strip()
    if ref.startswith("'"):
        end = ref.find("'", 1)
        table = ref[1:end]
        rest = ref[end + 1:].lstrip(".").strip()
    else:
        dot = ref.find(".")
        if dot == -1:
            return ref, ""
        table, rest = ref[:dot], ref[dot + 1:].strip()
    return table, _unquote(rest)


# ─── Parsing do modelo (TMDL) ─────────────────────────────────────────────────


def _parse_table_file(text: str) -> Optional[dict[str, Any]]:
    """Interpreta um arquivo ``tables/<Tabela>.tmdl``.

    Returns:
        dict com ``name``, ``isHidden``, ``columns`` (lista de
        ``{name, expression}``), ``measures`` (lista de ``{name, expression}``)
        e ``mExpression`` (M da partição import), ou ``None`` se não houver tabela.
    """
    root = _build_tree(text)
    table_node = next(
        (n for n in root["children"] if n["text"].startswith("table ")), None
    )
    if table_node is None:
        return None

    name = _decl_name(table_node["text"], "table")
    is_hidden = False
    columns: list[dict[str, str]] = []
    measures: list[dict[str, str]] = []
    m_expression = ""

    for child in table_node["children"]:
        header = child["text"]
        if header == "isHidden" or header.startswith("isHidden:"):
            is_hidden = True
        elif header.startswith("column "):
            col_name = _decl_name(header, "column")
            expression = _value_after_eq(child) if "=" in header else ""
            props = _child_props(child)
            columns.append({
                "name": col_name,
                "expression": expression,
                "dataType": props.get("dataType", ""),
                "formatString": props.get("formatString", ""),
                "isHidden": props.get("isHidden", "").lower() == "true",
            })
        elif header.startswith("measure "):
            measure_name = _decl_name(header, "measure")
            measures.append({"name": measure_name, "expression": _value_after_eq(child)})
        elif header.startswith("partition "):
            source_node = next(
                (c for c in child["children"] if c["text"].startswith("source")), None
            )
            if source_node is not None:
                m_expression = _value_after_eq(source_node)

    return {
        "name": name,
        "isHidden": is_hidden,
        "columns": columns,
        "measures": measures,
        "mExpression": m_expression,
    }


def _parse_relationships(text: str) -> list[dict[str, Any]]:
    """Interpreta ``relationships.tmdl`` para registros compatíveis com o backend."""
    root = _build_tree(text)
    result: list[dict[str, Any]] = []
    for node in root["children"]:
        if not node["text"].startswith("relationship "):
            continue
        props: dict[str, str] = {}
        for child in node["children"]:
            match = re.match(r"^([A-Za-z]+)\s*:\s*(.*)$", child["text"])
            if match:
                props[match.group(1)] = match.group(2).strip()

        from_column = props.get("fromColumn", "")
        to_column = props.get("toColumn", "")
        if not from_column or not to_column:
            continue
        from_table, from_col = _split_ref(from_column)
        to_table, to_col = _split_ref(to_column)

        # Cardinalidade: padrão TMDL é muitos-para-um (from=many, to=one).
        from_card = props.get("fromCardinality", "many").lower()
        to_card = props.get("toCardinality", "one").lower()
        cardinality = {
            ("many", "one"): "M:1",
            ("one", "many"): "1:M",
            ("one", "one"): "1:1",
            ("many", "many"): "M:M",
        }.get((from_card, to_card), "M:1")

        # Filtro cruzado: padrão é direção única; só "bothDirections" é bidirecional.
        cross = props.get("crossFilteringBehavior", "").lower()
        cross_filter = "both" if cross == "bothdirections" else "single"

        is_active = props.get("isActive", "true").lower() != "false"

        result.append({
            "FromTableName": from_table,
            "FromColumnName": from_col,
            "ToTableName": to_table,
            "ToColumnName": to_col,
            "Cardinality": cardinality,
            "CrossFilteringBehavior": cross_filter,
            "IsActive": is_active,
        })
    return result


def _parse_expressions(text: str) -> list[dict[str, str]]:
    """Interpreta ``expressions.tmdl`` (queries M compartilhadas/parâmetros)."""
    root = _build_tree(text)
    result: list[dict[str, str]] = []
    for node in root["children"]:
        if node["text"].startswith("expression "):
            name = _decl_name(node["text"], "expression")
            result.append({"TableName": name, "Expression": _value_after_eq(node)})
    return result


# ─── Parsing do relatório (PBIR) ──────────────────────────────────────────────

_REF_PATTERNS = [
    re.compile(r'"Entity"\s*:\s*"([^"]+)"'),
    re.compile(r'"Property"\s*:\s*"([^"]+)"'),
    re.compile(r'"Measure"\s*:\s*"([^"]+)"'),
    re.compile(r'"Column"\s*:\s*"([^"]+)"'),
]


def _extract_visual_refs(raw: str) -> set[str]:
    """Extrai nomes de entidades/colunas/medidas referenciadas em um visual PBIR."""
    refs: set[str] = set()
    for pattern in _REF_PATTERNS:
        for match in pattern.finditer(raw):
            value = match.group(1)
            refs.add(value.lower())
            for part in re.split(r"[.\[\]]+", value):
                clean = part.strip("'\" ")
                if clean:
                    refs.add(clean.lower())
    return refs


def _visual_descriptor(visual_json: dict[str, Any], folder_name: str) -> tuple[str, str]:
    """Devolve (título, tipo) de um ``visual.json`` PBIR, com fallbacks."""
    visual = visual_json.get("visual", {}) if isinstance(visual_json, dict) else {}
    visual_type = visual.get("visualType") or "Visual"
    title = ""
    try:
        objects = visual.get("visualContainerObjects", {})
        title_props = objects.get("title", [{}])[0].get("properties", {})
        literal = title_props.get("text", {}).get("expr", {}).get("Literal", {})
        title = str(literal.get("Value", "")).strip("'")
    except Exception:  # noqa: BLE001 - título é meramente cosmético
        title = ""
    if not title:
        title = f"{visual_type} {folder_name[:6]}"
    return title, visual_type


def _read_report(report_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Lê páginas e visuais do relatório PBIR.

    Returns:
        (pages, visuals) onde page = ``{name, ordinal, visualCount, width, height}``
        e visual = ``{name, type, refs}``.
    """
    pages_dir = report_dir / "definition" / "pages"
    if not pages_dir.is_dir():
        return [], []

    meta_path = pages_dir / "pages.json"
    page_order: list[str] = []
    if meta_path.exists():
        try:
            page_order = json.loads(meta_path.read_text(encoding="utf-8")).get("pageOrder", [])
        except Exception as error:  # noqa: BLE001
            logger.warning("Falha ao ler pages.json: %s", error)

    by_id = {p.name: p for p in pages_dir.iterdir() if p.is_dir()}
    ordered_ids = page_order + [pid for pid in by_id if pid not in page_order]

    pages: list[dict[str, Any]] = []
    visuals: list[dict[str, Any]] = []
    for ordinal, page_id in enumerate(ordered_ids):
        folder = by_id.get(page_id)
        if folder is None:
            continue
        try:
            page_json = json.loads((folder / "page.json").read_text(encoding="utf-8"))
        except Exception as error:  # noqa: BLE001
            logger.warning("Falha ao ler page.json de %s: %s", page_id, error)
            continue

        visuals_dir = folder / "visuals"
        visual_folders = (
            [v for v in visuals_dir.iterdir() if v.is_dir()]
            if visuals_dir.is_dir()
            else []
        )
        pages.append({
            "name": page_json.get("displayName") or page_id,
            "ordinal": ordinal,
            "visualCount": len(visual_folders),
            "width": int(page_json.get("width", 1280)),
            "height": int(page_json.get("height", 720)),
        })

        for visual_folder in visual_folders:
            visual_path = visual_folder / "visual.json"
            if not visual_path.exists():
                continue
            raw = visual_path.read_text(encoding="utf-8")
            try:
                visual_json = json.loads(raw)
            except Exception:  # noqa: BLE001
                visual_json = {}
            title, visual_type = _visual_descriptor(visual_json, visual_folder.name)
            visuals.append({
                "name": title,
                "type": visual_type,
                "refs": sorted(_extract_visual_refs(raw)),
            })

    return pages, visuals


# ─── Localização e leitura do projeto ─────────────────────────────────────────


def find_project(path: Path) -> tuple[Optional[Path], Optional[Path]]:
    """Localiza as pastas ``*.SemanticModel`` e ``*.Report`` do projeto.

    Args:
        path: caminho de um arquivo ``.pbip``, de uma pasta de projeto, ou de
            uma pasta ``*.SemanticModel`` / ``*.Report``.

    Returns:
        Tupla ``(semantic_model_dir, report_dir)`` (qualquer um pode ser ``None``).
    """
    path = Path(path)
    if path.suffix.lower() == ".pbip":
        base = path.parent
    elif path.is_dir() and path.name.endswith((".SemanticModel", ".Report")):
        base = path.parent
    elif path.is_dir():
        base = path
    else:
        base = path.parent

    semantic = next(iter(sorted(base.glob("*.SemanticModel"))), None)
    report = next(iter(sorted(base.glob("*.Report"))), None)
    return semantic, report


def is_pbip(path: Path) -> bool:
    """Indica se o caminho aponta para um projeto ``.pbip`` (modelo TMDL presente)."""
    path = Path(path)
    if path.suffix.lower() == ".pbip":
        return True
    if path.is_dir():
        semantic, _ = find_project(path)
        return bool(semantic and (semantic / "definition").is_dir())
    return False


def read_project(path: Path) -> dict[str, Any]:
    """Lê um projeto ``.pbip`` e devolve os conjuntos de registros do modelo.

    Args:
        path: arquivo ``.pbip`` ou pasta do projeto.

    Returns:
        dict com ``power_query``, ``measures``, ``calc_columns``,
        ``relationships``, ``schema``, ``semantic_tables``, ``tables``,
        ``visuals``, ``pages`` e ``diagnostics``.

    Raises:
        FileNotFoundError: se a pasta ``*.SemanticModel/definition`` não existir.
    """
    semantic, report = find_project(Path(path))
    diagnostics: list[str] = []

    if semantic is None or not (semantic / "definition").is_dir():
        raise FileNotFoundError(
            f"Modelo TMDL (*.SemanticModel/definition) não encontrado a partir de: {path}"
        )

    definition = semantic / "definition"
    tables_dir = definition / "tables"

    power_query: list[dict[str, str]] = []
    measures: list[dict[str, str]] = []
    calc_columns: list[dict[str, str]] = []
    schema: list[dict[str, str]] = []
    semantic_tables: list[dict[str, Any]] = []
    table_names: list[str] = []

    if tables_dir.is_dir():
        for table_file in sorted(tables_dir.glob("*.tmdl")):
            parsed = _parse_table_file(table_file.read_text(encoding="utf-8"))
            if parsed is None:
                continue
            table_name = parsed["name"]
            table_names.append(table_name)
            semantic_tables.append({"Name": table_name, "IsHidden": parsed["isHidden"]})

            if parsed["mExpression"]:
                power_query.append({"TableName": table_name, "Expression": parsed["mExpression"]})

            for column in parsed["columns"]:
                schema.append({
                    "TableName": table_name,
                    "ColumnName": column["name"],
                    "DataType": column.get("dataType", ""),
                    "FormatString": column.get("formatString", ""),
                    "IsHidden": column.get("isHidden", False),
                    "Expression": column.get("expression", ""),
                })
                if column["expression"]:
                    calc_columns.append({
                        "TableName": table_name,
                        "Name": column["name"],
                        "Expression": column["expression"],
                    })

            for measure in parsed["measures"]:
                measures.append({
                    "TableName": table_name,
                    "Name": measure["name"],
                    "Expression": measure["expression"],
                })

    expressions_file = definition / "expressions.tmdl"
    if expressions_file.exists():
        power_query.extend(_parse_expressions(expressions_file.read_text(encoding="utf-8")))

    relationships_file = definition / "relationships.tmdl"
    relationships: list[dict[str, Any]] = []
    if relationships_file.exists():
        relationships = _parse_relationships(relationships_file.read_text(encoding="utf-8"))

    pages: list[dict[str, Any]] = []
    visuals: list[dict[str, Any]] = []
    if report is not None:
        pages, visuals = _read_report(report)
        diagnostics.append(f"PBIR report: {report.name}")
    else:
        diagnostics.append("Relatório PBIR (*.Report) não encontrado: páginas/visuais vazios.")

    diagnostics.append(f"TMDL model: {semantic.name}")
    diagnostics.append(f"Tabelas TMDL: {len(table_names)}")
    diagnostics.append(f"Medidas TMDL: {len(measures)}")
    diagnostics.append(f"Colunas calculadas TMDL: {len(calc_columns)}")
    diagnostics.append(f"Relacionamentos TMDL: {len(relationships)}")
    diagnostics.append(f"Queries M (partições + expressions): {len(power_query)}")
    diagnostics.append(f"Páginas PBIR: {len(pages)}")
    diagnostics.append(f"Visuais PBIR: {len(visuals)}")

    return {
        "power_query": power_query,
        "measures": measures,
        "calc_columns": calc_columns,
        "relationships": relationships,
        "schema": schema,
        "semantic_tables": semantic_tables,
        "tables": table_names,
        "visuals": visuals,
        "pages": pages,
        "diagnostics": diagnostics,
    }
