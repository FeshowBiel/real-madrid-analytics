"""
ETL Real Madrid Analytics
Extrai stats do FBref (Opta) + Understat via soccerdata e grava em SQLite.
Roda local ou no GitHub Actions.
"""
import sys
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import soccerdata as sd

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
TEAM = "Real Madrid"
LEAGUE = "ESP-La Liga"

# Temporada corrente — atualizada a cada rodada semanal
CURRENT_SEASON = "2026-2027"

# Temporadas anteriores — carga única, com --history
HISTORY_SEASONS = []  # vazio = so a temporada corrente. Para comparar anos,
# adicione aqui, ex: ["2025-2026"], e rode uma vez com --history

# --history baixa tudo; sem flag, só a temporada corrente (rápido)
HISTORY_MODE = "--history" in sys.argv
SEASONS = ([*HISTORY_SEASONS, CURRENT_SEASON] if HISTORY_MODE else [CURRENT_SEASON])

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "real_madrid.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("etl")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def flatten(df: pd.DataFrame) -> pd.DataFrame:
    """Achata MultiIndex de colunas e reseta o index."""
    df = df.reset_index()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            "_".join([str(p) for p in col if p and not str(p).startswith("Unnamed")]).strip("_")
            for col in df.columns
        ]
    df.columns = [str(c).replace(" ", "_").replace("%", "pct").lower() for c in df.columns]
    return df


def only_team(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra apenas o time alvo, seja qual for a coluna que carrega o nome."""
    for col in ("team", "squad", "home_team", "index"):
        if col in df.columns:
            mask = df[col].astype(str).str.contains(TEAM, case=False, na=False)
            if mask.any():
                return df[mask].copy()
    return df


def save(conn: sqlite3.Connection, df: pd.DataFrame, table: str) -> None:
    """
    Grava mantendo o histórico: apaga do banco apenas as temporadas que
    estão sendo carregadas agora e preserva as demais.
    """
    if df is None or df.empty:
        log.warning("Tabela %s veio vazia — mantendo dado anterior.", table)
        return

    df = df.copy()
    df["_ingested_at"] = datetime.now(timezone.utc).isoformat()

    season_col = next((c for c in df.columns if "season" in c), None)

    if season_col:
        try:
            old = pd.read_sql(f'SELECT * FROM "{table}"', conn)
        except Exception:
            old = pd.DataFrame()

        if not old.empty and season_col in old.columns:
            loaded = set(df[season_col].astype(str))
            kept = old[~old[season_col].astype(str).isin(loaded)]
            df = pd.concat([kept, df], ignore_index=True)
            log.info("   merge %-22s preservadas %d linhas antigas", table, len(kept))

    df.to_sql(table, conn, if_exists="replace", index=False)
    log.info("OK %-28s %5d linhas x %d colunas", table, len(df), len(df.columns))


def try_step(fn, table, conn):
    """Executa um passo do ETL sem derrubar o pipeline inteiro."""
    try:
        save(conn, fn(), table)
    except Exception as exc:  # noqa: BLE001
        log.error("FALHOU %s -> %s", table, exc)


# ----------------------------------------------------------------------
# Extract
# ----------------------------------------------------------------------
def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    fbref = sd.FBref(leagues=LEAGUE, seasons=SEASONS)

    # --- Time: agregados por temporada -------------------------------
    try_step(
        lambda: only_team(flatten(fbref.read_team_season_stats(stat_type="standard"))),
        "team_season_standard",
        conn,
    )
    try_step(
        lambda: only_team(flatten(fbref.read_team_season_stats(stat_type="shooting"))),
        "team_season_shooting",
        conn,
    )
    try_step(
        lambda: only_team(flatten(fbref.read_team_season_stats(stat_type="defense"))),
        "team_season_defense",
        conn,
    )

    # --- Jogadores: agregados por temporada --------------------------
    for stat in ["standard", "shooting", "passing", "defense", "possession", "misc", "keeper"]:
        try_step(
            lambda s=stat: only_team(flatten(fbref.read_player_season_stats(stat_type=s))),
            f"player_season_{stat}",
            conn,
        )

    # --- Calendário e resultados -------------------------------------
    schedule_raw = None
    try:
        schedule_raw = fbref.read_schedule()
        save(conn, only_team(flatten(schedule_raw)), "schedule")
    except Exception as exc:  # noqa: BLE001
        log.error("FALHOU schedule -> %s", exc)

    # --- Jogadores: por partida (o dado mais rico) -------------------
    # O FBref serve UMA PAGINA POR PARTIDA. Sem filtro, baixaria os 380
    # jogos da liga. Aqui restringimos aos ~38 jogos do Real Madrid por
    # temporada, o que corta ~90% do tempo de execucao.
    match_ids = None
    if schedule_raw is not None:
        try:
            sched = schedule_raw.reset_index()
            cols = [c for c in ("home_team", "away_team") if c in sched.columns]
            mask = False
            for c in cols:
                mask = mask | sched[c].astype(str).str.contains(TEAM, case=False, na=False)
            rm_games = sched[mask]
            if "game_id" in rm_games.columns:
                match_ids = rm_games["game_id"].dropna().unique().tolist()
                log.info("Partidas do %s a baixar: %d (de %d na liga)",
                         TEAM, len(match_ids), len(sched))
        except Exception as exc:  # noqa: BLE001
            log.warning("Nao consegui filtrar match_ids: %s", exc)

    for stat in ["summary", "passing", "defense", "possession"]:
        def _read(s=stat):
            if match_ids:
                df = fbref.read_player_match_stats(stat_type=s, match_id=match_ids)
            else:
                # fallback: baixa a liga toda e filtra depois (lento)
                log.warning("Sem match_ids — baixando a liga inteira para %s", s)
                df = fbref.read_player_match_stats(stat_type=s)
            return only_team(flatten(df))

        try_step(_read, f"player_match_{stat}", conn)

    # --- Understat: xG por chute -------------------------------------
    try:
        understat = sd.Understat(leagues=LEAGUE, seasons=SEASONS)
        try_step(lambda: only_team(flatten(understat.read_shot_events())), "shots", conn)
    except Exception as exc:  # noqa: BLE001
        log.error("Understat indisponível: %s", exc)

    # --- Metadado da execução ----------------------------------------
    pd.DataFrame(
        [{"run_at": datetime.now(timezone.utc).isoformat(), "team": TEAM, "league": LEAGUE}]
    ).to_sql("_etl_runs", conn, if_exists="append", index=False)

    conn.commit()
    conn.close()
    log.info("ETL concluído -> %s", DB_PATH)


if __name__ == "__main__":
    main()
