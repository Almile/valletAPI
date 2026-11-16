"""Preenche o campo ``geohash`` dos estacionamentos criados antes da busca por proximidade.

Execute uma única vez, a partir da pasta ``valletAPI``:

    python app/backfill_geohash.py

Para apenas listar o que seria alterado, sem gravar:

    python app/backfill_geohash.py --dry-run
"""

import argparse
import sys
from pathlib import Path

# Permite executar tanto como ``python app/backfill_geohash.py`` quanto
# como ``python -m app.backfill_geohash``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygeohash as pgh

from app.core.firebase import db

PRECISAO = 9


def _coordenadas(dados: dict) -> tuple[float, float] | None:
    latitude = dados.get("latitude")
    longitude = dados.get("longitude")

    endereco = dados.get("endereco")
    if isinstance(endereco, dict):
        latitude = latitude or endereco.get("latitude")
        longitude = longitude or endereco.get("longitude")

    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return None

    if latitude == 0.0 and longitude == 0.0:
        return None

    return latitude, longitude


def main() -> None:
    parser = argparse.ArgumentParser(description="Preenche geohash dos estacionamentos.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra os documentos que receberiam geohash sem gravar nada.",
    )
    args = parser.parse_args()

    if db is None:
        raise SystemExit("Não foi possível conectar ao Firebase. Verifique FIREBASE_CREDENTIALS_PATH.")

    atualizados = ignorados = sem_coordenadas = 0

    for doc in db.collection("estacionamento").stream():
        dados = doc.to_dict() or {}

        if dados.get("geohash"):
            ignorados += 1
            continue

        coords = _coordenadas(dados)
        if coords is None:
            sem_coordenadas += 1
            print(f"[SEM COORDENADAS] {doc.id}")
            continue

        latitude, longitude = coords
        geohash = pgh.encode(latitude=latitude, longitude=longitude, precision=PRECISAO)

        if args.dry_run:
            print(f"[DRY-RUN] {doc.id} -> {geohash}")
        else:
            doc.reference.update({"geohash": geohash})
            print(f"[OK] {doc.id} -> {geohash}")

        atualizados += 1

    acao = "seriam atualizados" if args.dry_run else "atualizados"
    print(
        f"\nResumo: {atualizados} {acao}, {ignorados} já possuíam geohash, "
        f"{sem_coordenadas} sem coordenadas válidas."
    )


if __name__ == "__main__":
    main()
