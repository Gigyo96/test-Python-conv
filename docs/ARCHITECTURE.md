# IELTS Speaking Examiner — Architettura

Simulatore conversazionale dell'esame IELTS Speaking. L'utente parla in inglese,
un esaminatore sintetico conduce l'esame completo (Part 1/2/3) rispettando
formato, script e tempi reali, e al termine produce una valutazione indicativa
sui quattro criteri ufficiali.

---

## 1. Obiettivi e vincoli

### Obiettivi

| # | Obiettivo | Metrica di successo |
|---|---|---|
| O1 | Realismo conversazionale | Latenza percepita fine-turno → voce ≤ 900 ms sui turni scriptati |
| O2 | Fedeltà al formato d'esame | Sequenza, script e timer identici all'esame reale |
| O3 | Turn-taking corretto | Zero interruzioni spurie durante la Part 2 long turn |
| O4 | Valutazione utile | Band score sui 4 criteri con evidenze citate e timestamp |
| O5 | Struttura solida | Policy di turn-taking e FSM testabili senza audio né rete |

### Vincoli

- **Niente cuffie obbligatorie.** L'utente usa altoparlanti → serve echo cancellation reale.
- **Provider unico: Google.** Una sola credenziale per STT, TTS e LLM.
- **Un solo comando di avvio.** `python -m ielts_examiner` deve bastare.

### Non-obiettivi (v1)

- Multi-utente, deploy remoto, autenticazione.
- Valutazione certificata. I band score sono **indicativi** (§9.4).
- Lingue diverse dall'inglese.

---

## 2. Decisioni chiave

| ID | Decisione | Motivazione | Alternative scartate |
|---|---|---|---|
| D1 | **Frontend audio nel browser**, cervello in Python | L'AEC di WebRTC è l'unico echo canceller industriale accessibile gratuitamente e cross-platform. In più abilita la cue card visiva della Part 2. | `sounddevice` + AEC Python: il problema difficile è la stima del delay far-end, che dipende da driver e buffer e cambia a runtime. Le binding esistenti sono semi-abbandonate. |
| D2 | **`noiseSuppression: false`, `autoGainControl: false`, `echoCancellation: true`** | L'AEC è pass-through durante il turno del candidato (nessun segnale far-end da sottrarre) e non ne degrada lo spettro. NS e AGC invece alterano proprio le caratteristiche che il rater di pronuncia deve valutare. | Doppio `getUserMedia` (processato + raw): comportamento dipendente dal browser, complessità non giustificata. |
| D3 | **VAD locale** (Silero ONNX), tutto il resto cloud | Un endpointing lato server aggiungerebbe 200–400 ms sul percorso più critico e toglierebbe il controllo sulle soglie per fase, che è il cuore del progetto (§4). Silero: 1 MB, <1 ms/frame su CPU. | VAD server-side; WebRTC VAD (troppi falsi positivi sul parlato esitante). |
| D4 | **Service account GCP**, non API key AI Studio | Unica credenziale per Speech-to-Text v2, Text-to-Speech e Gemini via Vertex AI. Una key AI Studio coprirebbe solo Gemini. | API key AI Studio + seconda credenziale per STT/TTS. |
| D5 | **Pipeline a cascata** come backend di default; Gemini Live dietro allo stesso `Protocol`, come flag sperimentale | La prosodia espressiva di un modello speech-to-speech è *stilisticamente sbagliata* per un esaminatore IELTS, che legge da script con tono deliberatamente neutro e standardizzato. In più la Live API toglie il controllo deterministico sul turn-taking. | Live API come default. |
| D6 | **Question bank statica curata**, LLM solo per selezione topic e fallback | L'esame reale pesca da un pool fisso. Una bank statica è interamente pre-sintetizzabile e rende le sessioni **riproducibili**, quindi i band score confrontabili nel tempo. | Generazione LLM di tutte le domande: deriva stilistica, nessuna cache, nessuna riproducibilità. |
| D7 | **Pre-sintesi aggressiva** di tutto ciò che è scriptato | Porta la latenza percepita dei turni scriptati da ~1.8 s a ~0.75 s (§5). | Sintesi live su ogni turno. |
| D8 | **Policy di turn-taking come funzione pura** | Rende testabile con una tabella di casi il componente più difficile da tarare. | Logica di endpointing intrecciata al loop audio. |
| D9 | **LangGraph per entrambi i grafi** | *Decisione debole, e va detto.* Nell'Assessor si guadagna il fan-out parallelo e il retry per nodo. Nel Director un FSM a mano basterebbe: LangGraph vale per checkpointing (ripresa d'esame), state reducer tipizzati e omogeneità col secondo grafo. Contestabile. | FSM a mano nel Director. |
| D10 | **Event log come unica fonte di verità** | L'assessment è rieseguibile offline; un crash a metà esame non perde i dati; abilita il replay (§11). | Stato solo in memoria. |
| D11 | **Zero toolchain JS** | HTML + JS vanilla + un AudioWorklet. Nessun npm, nessun bundler, nessun `node_modules`. | React/Vite: sproporzionato per tre file. |

---

## 3. Vista d'insieme

```
┌─ BROWSER (localhost) ─────────────┐        ┌─ PYTHON (asyncio) ──────────────────────────┐
│                                   │        │                                             │
│  getUserMedia                     │        │  SessionRunner                              │
│   AEC on / NS off / AGC off       │        │   ├── VAD (Silero)                          │
│  AudioWorklet → PCM16 16 kHz ─────┼─ WS ──►│   ├── TurnPolicy  ← funzione pura           │
│                                   │ binary │   ├── STT streaming (Google STT v2)         │
│  Cue card + timer prep            │        │   │                                         │
│  Stato esame              ◄───────┼─ WS ───┤   ├── DIRECTOR (LangGraph, interrupt())     │
│                                   │  json  │   │    possiede fase, script, timer, policy │
│  WebAudio playback        ◄───────┼─ WS ───┤   ├── SpeechCache + TTS streaming           │
│                                   │ binary │   └── Recorder → session dir                │
└───────────────────────────────────┘        │                                             │
                                             └──────────────────┬──────────────────────────┘
                                                                │ a fine esame
                                                                ▼
                                             ┌─ ASSESSOR (LangGraph, offline) ─────────────┐
                                             │  fan-out su 4 rater → aggregate → report    │
                                             └─────────────────────────────────────────────┘
```

Principio invariante: **il Director non tocca mai l'audio e il loop audio non chiama mai il Director in modo bloccante.** Il grafo gira nei buchi fra un turno e l'altro.

---

## 4. Il problema centrale: il turn-taking

È qui che il progetto si gioca. Un assistente vocale generico assume *pausa 700 ms = turno finito*. Applicata all'IELTS, questa euristica distrugge la simulazione: nella Part 2 il candidato parla due minuti da solo con pause di esitazione di 3–4 secondi e verrebbe interrotto quindici volte.

### 4.1 Soglie per fase

| Fase | Soglia base | Condizione di uscita dal turno |
|---|---|---|
| `INTRO` (ID check) | 700 ms | silenzio |
| `PART1` | 700 ms | silenzio |
| `PART2_PREP` | — | timer 60 s, microfono ignorato |
| `PART2_LONG_TURN` | 4000 ms | timer **120 s** (l'esaminatore *deve* interrompere) o silenzio prolungato |
| `PART2_ROUNDING` | 800 ms | silenzio |
| `PART3` | 1100 ms | silenzio |
| `CLOSING` | — | — |

### 4.2 Endpointing semantico

Sopra la soglia base, un ladder di aggiustamenti sul transcript parziale:

| Segnale | Effetto |
|---|---|
| Esitazione: filler vocale (`um`, `uh`, `erm`) o locuzione (`I mean`, `you know`, `sort of`) | **+800 ms** |
| Enunciato incompleto: preposizione, congiunzione subordinante, articolo, possessivo | **+500 ms** |
| Turno già oltre 25 s e ultimo token conclusivo | **−200 ms** |
| Energia in calo sugli ultimi 500 ms (proxy prosodico di conclusione) | **−150 ms** |

**Le liste sono deliberatamente conservative.** L'inglese è pieno di token che
sembrano incompleti ma chiudono normalmente una frase: *"Yes, I do"*, *"I think
so"*, *"No, I have not"*. Ogni falso positivo aggiunge mezzo secondo di vuoto
proprio agli scambi brevi di cui la Part 1 è fatta, quindi ausiliari e modali
sono **esclusi** dalla lista dei token incompleti. I discourse marker ambigui
(`well`, `so`, `like`, `right`) contano come esitazione solo finché il candidato
non ha detto nient'altro che filler: così *"Well…"* estende la soglia e *"I think
it went well"* no.

Sul segnale prosodico: il VAD rilascia qualche frame dopo la fine reale del
parlato, e quei frame quasi silenziosi falserebbero la pendenza a **ogni** fine
turno. La finestra di energia ignora quindi i frame sotto il 10% del proprio
picco — soglia relativa e non assoluta, così vale per chi parla piano come per
chi parla forte.

Deliberatamente euristico e a costo zero. Un modello di turn-detection sarebbe più preciso ma aggiungerebbe latenza sul percorso critico: valutabile in v2, misurando prima quanto sbaglia l'euristica sui dati di replay.

### 4.3 Forma del componente (D8)

```python
@dataclass(frozen=True, slots=True)
class TurnSignals:
    silence_ms: int
    speech_ms: int  # totale parlato nel turno
    contiguous_speech_ms: int  # run corrente ininterrotta
    phase_elapsed_ms: int
    partial_transcript: str
    energy_slope: float
    examiner_speaking: bool


class TurnDecision(StrEnum):
    KEEP_LISTENING
    ENDPOINT  # il candidato ha finito
    BARGE_IN  # il candidato sta parlando sopra l'esaminatore
    FORCE_STOP  # timer scaduto, l'esaminatore interrompe
    PROMPT_CONTINUE  # silenzio anomalo in Part 2, sollecito


def decide(signals: TurnSignals, phase: Phase, config: TurnConfig) -> TurnDecision: ...
```

Due contatori di parlato invece di uno, perché rispondono a domande diverse: il
guard anti-eco deve sapere se il candidato sta *sostenendo* la voce sopra
l'esaminatore (l'eco residuo è breve e frammentato), mentre la regola del turno
assestato guarda quanto è stato detto in totale.

Pura: nessun I/O, nessuno stato nascosto, nessun orologio interno. Tutto lo stato
mutabile vive in `TurnDetector`, che conta millisecondi e delega ogni giudizio.
Test in §12.1.

### 4.4 Soppressione dell'eco residuo a livello di policy

L'AEC del browser è ottimo ma non perfetto ad alto volume. Difesa in profondità:

- Durante il playback dell'esaminatore la soglia Silero sale da `0.5` a `0.85` e servono **300 ms di voce sostenuta** per dichiarare `BARGE_IN`. L'eco residuo è a bassa energia e frammentato: non supera il doppio filtro.
- Durante il playback **lo STT non viene alimentato**: nessun rischio che l'esaminatore trascriva sé stesso, e nessun costo.
- Costo: 300 ms di ritardo sul barge-in, invisibile — un esaminatore reale non si zittisce all'istante.

### 4.5 Asimmetria del barge-in

- **Candidato → esaminatore**: consentito, col guard di 300 ms.
- **Esaminatore → candidato**: il taglio a 120 s in Part 2 è **incondizionato**. È precisamente ciò che fa l'esaminatore reale.

---

## 5. Budget di latenza

```
Turno con sintesi live:
  endpoint 700 ms → STT final 250 ms → LLM TTFT 500 ms → TTS TTFB 350 ms  ≈ 1.8 s

Turno pre-sintetizzato (l'80% dei turni):
  endpoint 700 ms → playback immediato                                     ≈ 0.75 s
```

1.8 s di silenzio in un esame orale è una voragine. 0.75 s è indistinguibile da un umano.

### Il ritardo deliberato

Rispondere istantaneamente è **meno** realistico. Un esaminatore vero, dopo la risposta, annota sul modulo di valutazione per uno o due secondi. Introduciamo quindi un `response_delay` per fase (`PART1` ~600 ms, `PART3` ~1000 ms), eventualmente con un leggero rumore di carta. Il risultato è più umano di un sistema a latenza zero.

Backchannel pre-sintetizzati e neutri — *"Mm-hm."*, *"Right."*, *"Thank you."* — riprodotti dalla cache. **Mai valutativi** (§7.3).

### Strumentazione

Ogni turno scrive in `metrics.jsonl`: `endpoint_at`, `stt_final_at`, `llm_first_token_at`, `tts_first_chunk_at`, `playback_start_at`, `cache_hit`. Il realismo si misura, non si presume.

---

## 6. Il grafo Director

### 6.1 Flusso

```
INTRO ──► PART1_TOPIC[1..3] ──► TRANSITION ──► PART2_CUECARD
   ▲                                                │
   │                                                ▼
CLOSING ◄── PART3_DISCUSSION ◄── PART2_ROUNDING ◄── PART2_PREP(60s)
                                        ▲                │
                                        └── PART2_LONG_TURN(≤120s)
```

### 6.2 Pattern di esecuzione (D9)

Il grafo modella l'esame come flusso lineare e si **sospende** sul turno del candidato:

```python
# nel nodo
answer = interrupt({"expect": "candidate_turn", "phase": Phase.PART1, ...})
# il runtime esegue VAD/STT/timer e riprende con:
graph.invoke(Command(resume=CandidateTurn(...)), config=thread)
```

Con un checkpointer su SQLite si ottiene gratis la ripresa di un esame interrotto. Il grafo resta leggibile come sequenza d'esame invece di frammentarsi in callback.

### 6.3 State

```python
class DirectorState(TypedDict):
    phase: Phase
    exam_clock_ms: int
    phase_deadline_ms: int | None
    part1_topics: list[Topic]
    part1_cursor: tuple[int, int]  # (topic, domanda)
    cue_card: CueCard
    part3_tree: Part3Tree  # pre-generato e pre-sintetizzato
    part3_path: list[str]
    turns: Annotated[list[Turn], add]  # reducer append-only
    candidate_name: str | None
    flags: ExamFlags  # repeat usati, probe usati, ...
```

### 6.4 Conditional edges

| Condizione | Destinazione |
|---|---|
| Risposta troppo breve in Part 1 (< 8 parole) | `probe` — *"Why?"* / *"Can you tell me more about that?"* |
| Candidato non ha capito | `repeat_question` — l'esaminatore **ripete ma non spiega mai** (regola d'esame reale) |
| Silenzio > 8 s in Part 2 prima dei 60 s | `prompt_continue` |
| Budget della parte esaurito | transizione forzata alla parte successiva |

### 6.5 Budget-aware pruning

L'esame reale dura 11–14 minuti con budget per parte (Part 1: 4–5 min, Part 2: 3–4 min, Part 3: 4–5 min). Se il candidato è prolisso, il Director **taglia domande** invece di sforare: a ogni domanda verifica `tempo_residuo_parte` e salta al topic successivo quando serve. Un esaminatore reale fa esattamente così.

### 6.6 Pre-generazione a due stadi

| Momento | Cosa viene preparato |
|---|---|
| **Avvio sessione**, prima dell'INTRO | Selezione topic Part 1 + cue card dalla bank; sintesi TTS di *tutto* lo script fisso e di tutte le domande Part 1/2 |
| **Durante Part 2** (60 s prep + ≤120 s long turn = ~3 min di tempo morto) | Generazione e sintesi dell'**albero Part 3**: 3 temi × 3 domande × 2 probe ≈ 20 clip |

L'albero preserva l'adattività — il Director **naviga** invece di generare — mantenendo latenza zero. Generazione live solo se nessun ramo è pertinente: fallback raro e misurato via `metrics.jsonl`.

---

## 7. Contenuti

### 7.1 Question bank

YAML versionato in `content/banks/`. Ogni item: `id`, `text`, `topic`, `part`, `difficulty`, `tags`. La bank è l'unità di riproducibilità: fissando il `seed` della sessione si riottiene lo stesso esame.

### 7.2 Script dell'esaminatore

Formule verbatim, non parafrasi:

> *"Good morning. My name is ___. Can you tell me your full name, please?"*
> *"Now, I'm going to give you a topic and I'd like you to talk about it for one to two minutes. Before you talk you'll have one minute to think about what you're going to say. You can make some notes if you wish. Do you understand?"*
> *"Thank you. That is the end of the speaking test."*

### 7.3 Il prompt dell'esaminatore

Un LLM di default è un assistente gentile. **Un esaminatore IELTS non lo è.** Vincoli espliciti e non negoziabili nel system prompt:

- Nessun feedback, nessuna lode, nessuna correzione, nessun commento sul contenuto.
- Nessuna riformulazione d'aiuto. Ripetere è consentito, spiegare no.
- Backchannel neutri soltanto.
- Nessuna opinione propria, nessuna risposta a domande del candidato sull'esame.
- Tono uniforme per tutta la sessione.

Sbagliare questo prompt significa ottenere un chatbot simpatico invece di una simulazione d'esame. È l'errore più comune in progetti di questo tipo, e ha più impatto sul realismo percepito di qualunque scelta infrastrutturale.

### 7.4 Voce

Una sola voce `en-GB` per tutta la sessione, stessi parametri per clip in cache e sintesi live, altrimenti la giunzione si sente. Definita in un unico `VoiceProfile` in `config.py`.

> ⚠ Da verificare in implementazione: matrice esatta voce en-GB × supporto streaming del TTS Google.

---

## 8. Registrazione: event log come fonte di verità (D10)

```
sessions/2026-09-12T14-33-02Z/
├── manifest.json      # config, seed, versioni bank/prompt, voce, device
├── events.jsonl       # ★ fonte di verità, append-only, ogni riga timestamped
├── candidate.wav      # 16 kHz mono PCM16, traccia continua del microfono
├── examiner.wav       # traccia dell'esaminatore, per il mixdown
├── metrics.jsonl      # latenze per turno
├── transcript.json    # parole con timestamp e confidence
└── report.html        # prodotto dall'Assessor
```

Tipi di evento: `phase_enter`, `phase_exit`, `examiner_utterance`, `candidate_speech_start/end`, `stt_partial`, `stt_final`, `turn_decision`, `timer_fired`, `barge_in`, `error`.

Proprietà che ne derivano:
- L'**assessment è rieseguibile offline** senza rifare l'esame (prompt engineering sui rater a costo quasi nullo).
- Un crash a metà esame non perde nulla: audio e log sono già su disco.
- Se lo stream STT muore, l'esame prosegue e il transcript si ricostruisce offline dall'audio.
- Abilita il replay (§11).

---

## 9. Il grafo Assessor

### 9.1 Topologia

```
        ┌── Fluency & Coherence ──┐
prep ───┼── Lexical Resource ─────┼── aggregate ── report
 (map)  ├── Grammatical Range ────┤   (reduce)
        └── Pronunciation ────────┘
```

Il fan-out parallelo con retry per nodo è il punto in cui LangGraph si ripaga davvero.

### 9.2 Audio come evidenza primaria

**Tutti e quattro i rater ricevono l'audio**, non solo quello di pronuncia. Il transcript serve da indice temporale, non da sostituto. Motivo nel §9.3.

### 9.3 Correzione del bias di trascrizione

Un candidato con accento marcato genera errori STT; un rater che legge solo il transcript penalizza per errori grammaticali **mai pronunciati**. È il difetto sistematico degli scorer IELTS basati su LLM. Mitigazioni:

1. Audio come evidenza primaria (§9.2).
2. Le parole sotto soglia di confidence STT sono marcate `[unclear]` ed **escluse dal conteggio degli errori** di grammatica e lessico.
3. Il rater deve **citare l'evidenza prima di assegnare il punteggio** (evidence-then-score, mai l'inverso), con timestamp verificabile.

### 9.4 Onestà del risultato

Un LLM che assegna band IELTS ha un errore realistico di **±0.5–1.0 band** rispetto a un esaminatore certificato. Mitigazioni: descrittori di banda ufficiali nel prompt, evidence-then-score, temperatura bassa. Il report dichiara esplicitamente la natura indicativa del punteggio. Non vendiamo precisione che non abbiamo.

---

## 10. Struttura del repository

```
.
├── pyproject.toml                  # uv + ruff + pytest + mypy
├── README.md
├── .env.example
├── docs/
│   ├── ARCHITECTURE.md             # questo documento
│   └── decisions/                  # ADR per le scelte che cambieranno
├── src/ielts_examiner/
│   ├── __main__.py                 # avvia uvicorn, apre il browser          [M2]
│   ├── config.py                   # VoiceProfile, PhaseTuning, TurnConfig
│   ├── replay.py                   # ★ motore di replay (§11.2)
│   ├── domain/                     # tipi puri: nessun I/O, nessun framework
│   │   ├── phase.py                # Phase
│   │   └── turn.py                 # TurnSignals, TurnDecision
│   ├── turntaking/
│   │   ├── policy.py               # ★ decide() — funzione pura (§4.3)
│   │   ├── lexicon.py              # classificazione della coda dell'enunciato
│   │   └── detector.py             # shell stateful: solo contabilità
│   ├── audio/
│   │   ├── frames.py               # AudioFrame, framing PCM16
│   │   └── vad.py                  # Protocol + EnergyVad (Silero in M2)
│   ├── server/                                                            # [M2]
│   │   ├── app.py                  # FastAPI, mount statici
│   │   ├── protocol.py             # schema messaggi WS
│   │   └── session_runner.py       # orchestratore asyncio della sessione
│   ├── services/
│   │   ├── protocols.py            # SpeechToText / TextToSpeech / LanguageModel
│   │   ├── google_stt.py
│   │   ├── google_tts.py
│   │   ├── gemini.py
│   │   ├── live_backend.py         # Gemini Live, sperimentale (D5)
│   │   └── fakes.py                # implementazioni per test e CI senza credenziali
│   ├── graphs/                                                          # [M4/M5]
│   │   ├── director.py
│   │   ├── director_state.py
│   │   ├── assessor.py
│   │   └── assessor_state.py
│   ├── content/
│   │   ├── bank.py
│   │   ├── banks/{part1,part2,part3}.yaml
│   │   ├── script.py               # formule verbatim dell'esaminatore
│   │   └── prompts/                # examiner.md, rater_*.md, band_descriptors.md
│   ├── speech_cache.py             # pre-sintesi, cache su disco con chiave su (testo, voce)
│   ├── recording/
│   │   ├── events.py               # event log append-only
│   │   └── recorder.py             # WAV + manifest
│   └── report/render.py
├── web/
│   ├── index.html                  # sala d'esame, cue card, timer
│   ├── app.js                      # WS, stato UI
│   ├── capture-worklet.js          # AudioWorklet: 48k → 16k, PCM16
│   └── style.css
├── tests/
│   ├── test_turn_policy.py         # tabella di casi (§12.1)
│   ├── test_lexicon.py
│   ├── test_turn_detector.py
│   ├── test_audio.py
│   ├── test_events.py
│   ├── test_fakes.py
│   ├── test_replay.py
│   ├── test_director.py            # golden FSM (§12.2)                    [M4]
│   └── fixtures/synthetic_audio.py # audio con struttura nota
├── tools/
│   ├── replay.py                   # CLI sottile sopra ielts_examiner.replay
│   └── presynth.py                 # pre-popola la cache TTS dalla bank    [M3]
└── sessions/                       # output runtime, gitignored
```

Le voci marcate `[Mn]` non esistono ancora: arrivano nella milestone indicata.

---

## 11. Protocollo WebSocket e replay

### 11.1 Protocollo

Una sola connessione. **Frame binari = audio PCM16**; **frame testuali = JSON di controllo**.

Browser → server (JSON): `hello`, `ready`, `prep_done`, `error`.
Server → browser (JSON): `phase`, `cue_card`, `timer`, `examiner_speaking_start/end`, `transcript_partial`, `exam_end`.

Il browser è un terminale: non prende decisioni, rende lo stato che riceve.

### 11.2 Replay mode

`python tools/replay.py sessions/<id> --phase part2_long_turn` rimanda
`candidate.wav` attraverso VAD, TurnDetector e policy, e stampa ogni decisione
con il silenzio che l'ha giustificata.

Il replay **non è in tempo reale**: gira alla velocità della CPU e ricava ogni
timestamp dall'audio stesso, quindi è riproducibile e una differenza di
comportamento può venire solo da una modifica della policy.

Registra **transizioni, non livelli**. La policy è istantanea per costruzione,
quindi `ENDPOINT` resta vero per ogni frame della pausa che l'ha prodotto: ciò
che serve è l'istante in cui è *diventato* vero. La deduplicazione sta nel tool,
non nella policy, perché è l'assenza di stato nella policy a renderla testabile.

È il tool di sviluppo più importante del progetto: senza, tarare l'endpointing significa parlare al microfono cinquanta volte; con, è un test da due secondi. Va costruito nella prima milestone, non alla fine.

---

## 12. Strategia di test

### 12.1 Turn policy — tabella di casi

`decide()` è pura, quindi si testa con una tabella dichiarativa che codifica i casi difficili reali:

| Caso | Atteso |
|---|---|
| Part 2, silenzio 3500 ms, transcript finisce con `"and"` | `KEEP_LISTENING` |
| Part 2, silenzio 4200 ms, transcript conclusivo | `ENDPOINT` |
| Part 2, `phase_elapsed 120_001 ms` | `FORCE_STOP` |
| Part 1, silenzio 750 ms, transcript `"um"` | `KEEP_LISTENING` |
| Esaminatore parla, voce candidato 150 ms | `KEEP_LISTENING` (guard eco) |
| Esaminatore parla, voce candidato 350 ms | `BARGE_IN` |

### 12.2 Director — golden test

Una sequenza scriptata di `(utterance, durata)` in ingresso, la sequenza di azioni dell'esaminatore in uscita, confrontata con un file golden. Nessun audio, nessuna rete, esecuzione in millisecondi. Copre budget pruning, probe, repeat, transizioni forzate.

### 12.3 CI senza credenziali

`services/fakes.py` implementa i tre `Protocol`. L'intera suite gira senza GCP. I test di integrazione contro Google sono marcati e opt-in.

---

## 13. Configurazione e credenziali

Progetto GCP → abilita **Speech-to-Text**, **Text-to-Speech**, **Vertex AI** → service account → JSON → `GOOGLE_APPLICATION_CREDENTIALS`. Il codice usa ADC: nessun segreto nel repo.

```
GOOGLE_APPLICATION_CREDENTIALS=/path/sa.json
GOOGLE_CLOUD_PROJECT=...
GOOGLE_CLOUD_LOCATION=...
IELTS_MODEL_FAST=...      # classe Flash, probe live in Part 3
IELTS_MODEL_STRONG=...    # classe Pro, Assessor
IELTS_VOICE=...           # en-GB
```

Nessun nome di modello è hardcoded nel codice: solo config.

> ⚠ Da verificare in implementazione: ruoli IAM minimi per STT e TTS.

**Ordine di grandezza costi:** ~0.30–0.60 $ per esame completo, dominato dai ~14 minuti di STT. Indicativo, listini non verificati.

---

## 14. Rischi aperti

| Rischio | Impatto | Mitigazione |
|---|---|---|
| AEC del browser insufficiente ad alto volume | Barge-in spurio | Doppio filtro di policy (§4.4); avviso in UI se rileva eco persistente |
| Euristiche di endpointing semantico mal tarate | Interruzioni o attese innaturali | Corpus di replay + tabella di casi; iterare su dati, non a sensazione |
| Latenza STT variabile in rete | Salto oltre 1 s su turni live | Pre-sintesi copre l'80% dei turni; `metrics.jsonl` misura la coda |
| Band score fuori scala | Feedback fuorviante | §9.4, disclaimer esplicito nel report |
| Il prompt esaminatore "scivola" verso l'assistente gentile | Perdita di realismo | Vincoli espliciti (§7.3) + golden test sulle uscite |
| Deriva delle API Google | Rotture | Tutto dietro `Protocol`, un solo modulo per provider |

---

## 15. Milestone

| # | Contenuto | Criterio di uscita |
|---|---|---|
| **M1** ✅ | Scheletro, `Protocol` + fakes, event log, **replay mode**, `turn_policy` con tabella di casi | `pytest` verde senza credenziali; replay di una sessione sintetica |
| **M2** | Browser ↔ server: cattura AEC, WS, playback, VAD Silero | Loop eco-free end-to-end con TTS fake |
| **M3** | Servizi Google reali + speech cache + pre-sintesi | Latenza turni scriptati misurata ≤ 900 ms |
| **M4** | Director completo: tutte le fasi, timer, pruning, albero Part 3 | Esame completo 11–14 min, golden test verdi |
| **M5** | Assessor + report HTML | Report con 4 band, evidenze citate, timestamp |
| **M6** | Rifinitura realismo: backchannel, response delay, cue card UI | Sessione di valutazione soggettiva |
