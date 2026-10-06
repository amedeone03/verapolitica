# CEO demo video runbook

Record a **4:00–4:45** walkthrough of the local CEO demo.
Do not use the synthetic presenter dataset at `/demo/`.
Do not auto-publish. Do not present simulated AI as real.

Local recording shortcuts (demo UI only):

http://127.0.0.1:8000/demo/video

## Pre-recording

In a dedicated terminal:

```bash
cd /Users/ameboz/verapolitica
source .venv/bin/activate
set -a
source .env.ceo-demo
set +a
python -m scripts.reset_ceo_ai_demo
.venv/bin/python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Verify:

```bash
curl -s http://127.0.0.1:8000/health/ready
curl -s http://127.0.0.1:8000/proposals | python3 -c 'import sys,json; print(json.load(sys.stdin)["total"])'
ls -lh data/ceo_demo/demo.pdf
ollama list
```

Expected start state:

- health ready
- public proposals = **3** (ids 10, 21, 97)
- no operator AI drafts
- `data/ceo_demo/demo.pdf` still present (~5.1 MB)
- Ollama has `qwen3:8b`

Screen setup:

- 1440×900 or larger
- browser zoom 110% if titles feel small
- hide bookmarks bar
- keep `docs/CEO_DEMO_VIDEO.md` on a second screen
- file picker ready at `data/ceo_demo/demo.pdf`

## AI wait-time (legitimate options)

Real local extraction takes about **2–3 minutes**. Do not fake instant results.

**A. Preferred.** Record continuously. In post, speed up only the waiting portion
(about 8–12×) and keep one real timestamp on screen.

**B.** Record a clean before/after cut: click Analyze, stop; resume when the
pending draft appears. On camera, say that real local extraction ran.

If you ever use Deterministic demo fallback, say “this is simulated” immediately.

## Spoken script (condensed)

**0:00–0:30 — overview**
“VeraPolitica turns official public data into a single verifiable civic
information platform. Profiles, places, and proposals stay tied to their sources.”

**0:30–1:00 — politician**
“Here is a published senator. The profile is built from official records and
citations, not a self-edited politician page.”

**1:00–1:25 — municipality**
“The same model extends from national politics to territorial institutions.
Milano is in the official ISTAT reference.”

**1:25–1:50 — existing proposal**
“Every public claim remains traceable to official evidence: status, actor,
and the Senate source.”

**1:50–2:20 — upload**
“This is a real 1,188-page official Senate bill. Local AI will read it on this
computer. Nothing is published yet.”

**2:20–3:30 — processing**
“The full document is ingested. Two metadata sections are selected as evidence.
The model must copy exact excerpts. A second check can happen automatically.”

**3:30–4:15 — draft and review**
“The AI created a draft, never a publication. A human editor reviews the
evidence, then approves.”

**4:15–4:45 — public result**
“The approved information is now in the public archive, with the official
Senate page as source. Internal model details stay off the citizen page.”

---

## Scene-by-scene recording

### Scene 1 — Citizen platform · 0:00–0:30

Open:

http://127.0.0.1:8000/app/

Click: Politicians, Proposals, Municipalities, then return to the home list.
Hover the header search box.

Say: “VeraPolitica turns official public data into a single verifiable civic
information platform.”

Visible: verified politician cards, public navigation, search.

### Scene 2 — Politician · 0:30–1:00

In the header search, type `Sbrollini` and search.

Click **Daniela Sbrollini**.

Backup deep link:

http://127.0.0.1:8000/app/?politician=26

Scroll: personal facts, mandate, Official sources (13 references, Senato).

Say: “Profiles come from official sources and are not self-edited by politicians.”

Visible: “Verified from official sources”, Senate citations, Open official source.

### Scene 3 — Municipality · 1:00–1:25

Search `Milano`, filter or choose the municipality result.

Backup:

http://127.0.0.1:8000/app/?municipality=1772

Say: “The same model extends from national politics to territorial institutions.”

Visible: Comune di Milano, Lombardia, ISTAT code, official ISTAT source.
Mayor may read “not currently linked” — that is honest, not a bug.

### Scene 4 — Existing proposal · 1:25–1:50

Open Proposals, then proposal 97.

http://127.0.0.1:8000/app/?proposal=97

Scroll: status **Enacted**, actor **Governo Italiano**, official Senate source,
supporting evidence link.

Say: “Every public claim remains traceable to official evidence.”

Visible: title *Disposizioni per l'assestamento del bilancio dello Stato per
l'anno finanziario 2026*, no AI/model labels.

### Scene 5 — Real local AI · 1:50–3:30

Open:

http://127.0.0.1:8000/demo/ai-upload

Leave **REAL LOCAL AI** selected. Confirm model `qwen3:8b`.
Leave the official Senato URL as prefilled.
Do not check “Force a new AI run”.
Do not switch to Deterministic demo fallback.

Click **Choose PDF or HTML** and select `data/ceo_demo/demo.pdf`.

Say: “This is a real 1,188-page official Senate document.”

Click **Analyze**.

Watch:

1. Preparing official document
2. Full document: 1,188 pages
3. Selecting relevant evidence
4. Evidence selected: 2 relevant metadata sections
5. Running local AI — this can take around 2–3 minutes

Say, while waiting: “The full bill is ingested. Only the official metadata
needed to identify the bill is sent to local AI. Evidence must be copied
exactly. Nothing becomes public from this step.”

If a second pass runs, do not explain validators. Say: “A second check can
happen automatically before the draft is prepared.”

### Scene 6 — Pending draft · 3:30–3:55

When the draft opens, pause on:

- badge **Pending**
- “AI created an unpublished draft. Human review is required.”
- “Full document: 1,188 pages. Evidence selected: 2 relevant metadata sections.”
- official title
- exact excerpts
- actor **Governo Meloni-I**
- announced date
- target date none — no commitment deadline

Say: “The AI creates a draft, never a publication.”

Do not linger on the local model name. Do not open browser developer tools.

### Scene 7 — Human review · 3:55–4:15

Click **Start review**. Confirm the draft is still unpublished.

Click **Approve**.

Say: “A human editor reviews the evidence before anything becomes public.”

Visible: Approved, then **View published citizen page**.

### Scene 8 — Public result · 4:15–4:45

Click **View published citizen page**.

Show: public title, exact statement, official Senato link
`https://www.senato.it/leggi-e-documenti/disegni-di-legge/scheda-ddl?did=60485`.

Confirm there is no Ollama, qwen, prompt, or fingerprint text.

Say: “The approved information is now part of the public archive with full
provenance.”

Public proposal count is now **4**.

## Must stay manual

- choosing `demo.pdf`
- clicking Analyze
- waiting for real Ollama
- Start review
- Approve

No browser automation is included for those steps.

## After recording

```bash
cd /Users/ameboz/verapolitica
source .venv/bin/activate
set -a
source .env.ceo-demo
set +a
python -m scripts.reset_ceo_ai_demo
```

Confirm public proposals = **3** again.
`data/ceo_demo/demo.pdf` remains for the next take.

## Troubleshooting

- Ollama not running: start `ollama serve`. Do not silently switch to simulated mode.
- Wrong public count before recording: run the reset command above.
- `/demo/` shows Luca Bianchi / synthetic dataset: close it; that is a different demo.
- Title wrapping looks tight: zoom the browser, do not crop evidence blocks.
