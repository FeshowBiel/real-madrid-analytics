# Real Madrid Analytics

Pipeline ELT gratuito de estatísticas do Real Madrid (time e atletas).

**Stack:** Python + soccerdata (FBref/Opta + Understat) → SQLite → Streamlit
**Orquestração:** GitHub Actions (seg e qui, 06h BRT)

## Rodar local

```bash
python -m pip install -r requirements.txt

python src/etl.py --history   # carga inicial: 2023-24 ate 2026-27 (1x so)
python src/etl.py             # atualizacao: so a temporada 2026-2027

streamlit run app/streamlit_app.py
```

## Modos de execução

| Comando | O que faz | Quando usar |
|---|---|---|
| `python src/etl.py --history` | Baixa 4 temporadas | Uma vez, na carga inicial |
| `python src/etl.py` | Só a temporada corrente | Toda semana (é o que o Actions roda) |

O ETL faz merge por temporada: atualizar 2026-2027 não apaga os anos anteriores
já gravados no banco.

## Estrutura

```
src/etl.py             extração + carga no SQLite
app/streamlit_app.py   dashboard
data/real_madrid.db    banco (versionado)
.github/workflows/     cron diário
```

## Tabelas geradas

| Tabela | Conteúdo |
|---|---|
| team_season_* | agregados do time (standard, shooting, defense) |
| player_season_* | agregados por atleta (7 categorias) |
| player_match_* | stats por atleta por partida |
| schedule | calendário e resultados |
| shots | eventos de chute com xG e coordenadas (Understat) |
| _etl_runs | log de execuções |

Dados: FBref/Opta e Understat. Uso pessoal/portfólio, sem redistribuição comercial.
