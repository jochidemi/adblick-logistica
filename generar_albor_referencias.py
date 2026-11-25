#!/usr/bin/env python3
"""Genera albor_referencias.json deduplicado a partir de ImportacionCosecha.xlsx."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import tempfile
from pathlib import Path

import openpyxl

SOURCE_XLSX = Path(__file__).resolve().parent / "ImportacionCosecha.xlsx"
OUTPUT_JSON = Path(__file__).resolve().parent / "albor_referencias.json"

# Mapeo de columnas de la hoja 'Referencias' (1-based) a claves semanticas en JSON.
# Varias columnas de 'Referencias' son identicas entre si y se deduplican aqui.
REFERENCIAS_MAP: dict[str, tuple[int, str]] = {
    "tipo_comprobante": (1, "Código tipo de comprobante"),       # A
    "tipo_cpe": (2, "Tipo CPE"),                                 # B
    "sucursal_cpe": (3, "Numerador CPE"),                        # C
    "campana": (5, "Código campaña"),                            # E
    "especie": (6, "Código especie"),                            # F
    "cultivo": (8, "Código cultivo"),                            # H
    "deposito": (9, "Código depósito"),                          # I
    "contrato": (10, "Código contrato"),                         # J
    "transportista": (15, "Código transportista"),               # O (identica a P)
    "si_no": (17, "Mercaderia No Fumigada"),                     # Q (identica a Y)
    "entregador_remitente": (18, "Código entregador"),           # R (identica a S y T)
    "remitente_sec_dest": (21, "Código Remitente Comercial Venta Secundaria"),  # U (identica a V, W y AD)
    "pais": (26, "Código país"),                                 # Z
    "provincia": (27, "Código provincia"),                       # AA
    "localidad": (28, "Código localidad procedencia"),           # AB
    "partido": (29, "Código partido"),                           # AC
    "destino": (31, "Código destino"),                           # AE
    "catac": (33, "Código CATAC"),                               # AG
    "chofer": (34, "Chofer (CUIT)"),                              # AH
    "corredor": (37, "Código corredor"),                         # AK
}


def load_workbook_safe(path: Path) -> tuple[openpyxl.Workbook, Path | None]:
    """Abre el .xlsx directamente o via copia FileShare.ReadWrite si Excel lo tiene abierto."""
    try:
        return openpyxl.load_workbook(path, read_only=True, data_only=True), None
    except PermissionError:
        fd, tmp_name = tempfile.mkstemp(prefix="albor_refs_", suffix=".xlsx")
        os.close(fd)
        tmp_path = Path(tmp_name)
        ps_cmd = (
            f"$fs=[System.IO.File]::Open('{str(path).replace("'", "''")}',"
            "[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,"
            "([System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete));"
            f"$out=[System.IO.File]::Create('{str(tmp_path).replace("'", "''")}');"
            "$fs.CopyTo($out);$out.Close();$fs.Close()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            check=True,
        )
        return openpyxl.load_workbook(tmp_path, read_only=True, data_only=True), tmp_path


def dedup_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        clean = str(raw).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def build_referencias_json(xlsx_path: Path = SOURCE_XLSX, out_path: Path = OUTPUT_JSON) -> dict:
    wb, tmp_path = load_workbook_safe(xlsx_path)
    try:
        ws_main = wb["Cosechas a importar"]
        ws_refs = wb["Referencias"]

        first_row = next(ws_main.iter_rows(min_row=1, max_row=1, values_only=True))
        headers = [str(v).strip() if v is not None else "" for v in first_row]
        while headers and headers[-1] == "":
            headers.pop()

        if len(headers) != 90:
            raise ValueError(f"Se esperaban 90 columnas en 'Cosechas a importar', pero se encontraron {len(headers)}.")

        # Leer todas las columnas necesarias de Referencias en una sola pasada
        max_col = max(col_idx for col_idx, _ in REFERENCIAS_MAP.values())
        col_buckets: dict[int, list[str]] = {col_idx: [] for col_idx, _ in REFERENCIAS_MAP.values()}

        ref_rows = ws_refs.iter_rows(min_row=1, max_col=max_col, values_only=True)
        ref_header_row = next(ref_rows)
        for key, (col_idx, expected_hdr) in REFERENCIAS_MAP.items():
            actual_hdr = str(ref_header_row[col_idx - 1] or "").strip()
            if actual_hdr != expected_hdr:
                raise ValueError(
                    f"Header inesperado en Referencias col {col_idx} ({key}): "
                    f"esperaba {expected_hdr!r}, encontre {actual_hdr!r}"
                )

        for row in ref_rows:
            for col_idx in col_buckets:
                val = row[col_idx - 1] if col_idx - 1 < len(row) else None
                if val is not None:
                    s = str(val).strip()
                    if s:
                        col_buckets[col_idx].append(s)

        lists: dict[str, list[str]] = {}
        for key, (col_idx, _) in REFERENCIAS_MAP.items():
            items = dedup_preserve_order(col_buckets[col_idx])
            if key == "si_no" and not items:
                items = ["Sí", "No"]
            lists[key] = items

        payload = {
            "version": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": xlsx_path.name,
            "headers": headers,
            "lists": lists,
        }

        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        return payload
    finally:
        wb.close()
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    data = build_referencias_json()
    size_kb = OUTPUT_JSON.stat().st_size / 1024
    print(f"Generado {OUTPUT_JSON.name} ({size_kb:.1f} KB), {len(data['headers'])} headers.")
    for k, v in data["lists"].items():
        print(f"  - {k}: {len(v)} items")
