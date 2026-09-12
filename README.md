# IELTS Speaking Examiner

Simulatore conversazionale dell'esame IELTS Speaking: si parla in inglese con un
esaminatore sintetico che conduce Part 1, 2 e 3 rispettando script e tempi reali,
e al termine produce una valutazione indicativa sui quattro criteri ufficiali.

Il design completo, con le decisioni e il perché di ciascuna, è in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Stato

**Milestone M1 completata.** Il nucleo di turn-taking, i contratti dei servizi,
il log di sessione e il replay esistono e sono testati. Non c'è ancora audio dal
vivo né esame eseguibile: quelli arrivano in M2 e M4.

| Milestone | | |
|---|---|---|
| M1 | ✅ | Nucleo turn-taking, protocolli, event log, replay |
| M2 | ⬜ | Browser ↔ server, cattura con echo cancellation, VAD Silero |
| M3 | ⬜ | Servizi Google, cache TTS, pre-sintesi |
| M4 | ⬜ | Grafo Director: fasi, timer, albero Part 3 |
| M5 | ⬜ | Grafo Assessor e report |
| M6 | ⬜ | Rifinitura del realismo |

## Setup

Nessuna credenziale serve fino a M3: tutta la suite gira sui fake.

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

## Il replay

Lo strumento centrale dello sviluppo. Rimanda una registrazione attraverso VAD,
detector e policy e mostra ogni decisione con il silenzio che l'ha giustificata,
così l'endpointing si tara su dati invece che a memoria.

```bash
python tools/replay.py sessions/<id> --phase part2_long_turn
```

La stessa registrazione va letta diversamente a seconda della fase, ed è la
proprietà che il progetto esiste per garantire:

```
$ python tools/replay.py sessions/demo --phase part1
  42.82s  endpoint   silence=  500ms   speech= 42040ms
  71.32s  endpoint   silence=  500ms   speech= 67080ms

$ python tools/replay.py sessions/demo --phase part2_long_turn
  74.62s  endpoint   silence= 3800ms   speech= 67080ms
```

In Part 1 la pausa di 3,5 s chiude il turno; nel long turn della Part 2 viene
correttamente ignorata, perché lì interrompere il candidato a metà monologo
sarebbe un errore d'esame.

## Struttura

```
src/ielts_examiner/
  domain/       tipi puri, nessun I/O
  turntaking/   policy (funzione pura) + detector (solo contabilità)
  audio/        framing PCM16 e voice activity detection
  services/     protocolli STT/TTS/LLM e fake per la CI
  recording/    event log append-only e layout di sessione
  replay.py     motore di replay
tools/replay.py CLI
```

## Qualità

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy src tools
.venv/bin/python -m pytest
```
