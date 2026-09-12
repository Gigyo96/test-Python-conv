# IELTS Speaking Examiner

Simulatore conversazionale dell'esame IELTS Speaking: si parla in inglese con un
esaminatore sintetico che conduce Part 1, 2 e 3 rispettando script e tempi reali,
e al termine produce una valutazione indicativa sui quattro criteri ufficiali.

Il design completo, con le decisioni e il perché di ciascuna, è in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Stato

**Milestone M2 completata.** Il loop audio gira end-to-end in un browser reale:
cattura con echo cancellation, rilevamento di fine turno, voce dell'esaminatore,
registrazione della sessione. Le domande sono ancora un segnaposto e la voce è
muta: l'esame vero arriva con M3 e M4.

| Milestone | | |
|---|---|---|
| M1 | ✅ | Nucleo turn-taking, protocolli, event log, replay |
| M2 | ✅ | Browser ↔ server, cattura con echo cancellation, VAD Silero |
| M3 | ⬜ | Servizi Google, cache TTS, pre-sintesi |
| M4 | ⬜ | Grafo Director: fasi, timer, albero Part 3 |
| M5 | ⬜ | Grafo Assessor e report |
| M6 | ⬜ | Rifinitura del realismo |

## Setup

Nessuna credenziale serve fino a M3: tutta la suite gira sui fake.

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
curl -sSL --create-dirs -o ~/.cache/ielts-examiner/silero_vad.onnx \
  https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx
.venv/bin/python -m pytest
```

## Avvio

```bash
python -m ielts_examiner
```

Apre la sala d'esame nel browser. Usa pure gli altoparlanti: l'echo
cancellation è gestita dalla pagina, non servono cuffie.

Il browser non è un vezzo. Il suo cancellatore d'eco WebRTC è l'unico
industriale accessibile gratuitamente e multipiattaforma, e senza di quello gli
altoparlanti rimandano la voce dell'esaminatore nel microfono e il rilevatore di
fine turno scatta sulle parole dell'esaminatore stesso. Vedi la decisione D1.

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
  audio/        framing PCM16, gate condiviso, EnergyVad e SileroVad
  server/       protocollo WS, transport, driver, orchestratore di sessione
  services/     protocolli STT/TTS/LLM e fake per la CI
  recording/    event log append-only, tracce WAV, layout di sessione
  replay.py     motore di replay
web/            pagina d'esame: HTML, CSS, un worklet. Nessun build step.
tools/replay.py CLI
```

## Qualità

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy src tools
.venv/bin/python -m pytest          # veloce, senza credenziali né browser
.venv/bin/python -m pytest -m browser   # guida un Chromium reale
```

I test browser sono esclusi per default. Se il tuo Chromium non corrisponde alla
build attesa da Playwright, indicalo con `IELTS_CHROMIUM=/percorso/a/chrome`.

**Quello che i test non provano.** L'echo cancellation non è verificabile in
automatico: il dispositivo audio simulato di Chromium non ha percorso acustico,
quindi niente rimanda l'altoparlante nel microfono. La decisione D1 resta da
validare su hardware reale, ed è la prima cosa da controllare. Allo stesso modo
Silero non è esercitato dalle fixture: il rumore sintetico non è parlato, e un
rilevatore neurale giustamente si rifiuta di chiamarlo tale.
