"""Write the expanded official-evidence gold manifest. Never publishes."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "pledge_evidence" / "gold"

ACTOR = "Giorgia Meloni"
ANN = "2022-10-25"
CLASS = {
    "specificity": "high",
    "commitment_type": "action",
    "holder_role": "government_coalition",
}

P = {
    "101": {
        "commitment_id": "101",
        "commitment_title": "Tutelare le infrastrutture strategiche nazionali assicurando la proprietà pubblica",
        "commitment_text": (
            "Intendiamo tutelare le infrastrutture strategiche nazionali assicurando la "
            "proprietà pubblica delle reti, sulle quali le aziende potranno offrire servizi "
            "in regime di libera concorrenza, a partire da quella delle comunicazioni."
        ),
        "topic_code": "10",
        **CLASS,
    },
    "102": {
        "commitment_id": "102",
        "commitment_title": "Introdurre una clausola di salvaguardia dell'interesse nazionale",
        "commitment_text": (
            "E vogliamo finalmente introdurre una clausola di salvaguardia dell'interesse "
            "nazionale, anche sotto l'aspetto economico, per le concessioni di infrastrutture "
            "pubbliche, come autostrade e aeroporti."
        ),
        "topic_code": "10",
        **CLASS,
    },
    "103": {
        "commitment_id": "103",
        "commitment_title": "Certezza della pena e nuovo piano carceri",
        "commitment_text": (
            "Lavoreremo per restituire ai cittadini la garanzia di vivere in una Nazione "
            "sicura, rimettendo al centro il principio fondamentale della certezza della pena, "
            "grazie anche a un nuovo piano carceri."
        ),
        "topic_code": "12",
        **CLASS,
    },
    "104": {
        "commitment_id": "104",
        "commitment_title": "Rivedremo anche la riforma dell'ordinamento giudiziario",
        "commitment_text": (
            "Con la stessa determinazione rivedremo anche la riforma dell'ordinamento "
            "giudiziario, per mettere fine alle logiche correntizie che minano la "
            "credibilità della magistratura italiana."
        ),
        "topic_code": "12",
        **CLASS,
    },
    "105": {
        "commitment_id": "105",
        "commitment_title": "Modificare i criteri di valutazione dell'Agenzia delle entrate",
        "commitment_text": (
            "È la ragione per la quale intendiamo partire da una modifica dei criteri di "
            "valutazione dei risultati dell'Agenzia delle entrate, che vogliamo ancorare "
            "agli importi effettivamente incassati e non alle semplici contestazioni, come "
            "incredibilmente è avvenuto finora."
        ),
        "topic_code": "1",
        **CLASS,
    },
    "106": {
        "commitment_id": "106",
        "commitment_title": "Dare seguito al processo virtuoso di autonomia differenziata",
        "commitment_text": (
            "Parallelamente alla riforma presidenziale, intendiamo dare seguito al processo "
            "virtuoso di autonomia differenziata già avviato da diverse regioni italiane "
            "secondo il dettato costituzionale e in attuazione dei principi di sussidiarietà "
            "e solidarietà, in un quadro di coesione nazionale."
        ),
        "topic_code": "20",
        **CLASS,
    },
    "107": {
        "commitment_id": "107",
        "commitment_title": "Mantenere e migliorare il sostegno economico per i soggetti fragili",
        "commitment_text": (
            "È questa la strada che intendiamo percorrere: vogliamo mantenere e, laddove "
            "possibile, migliorare il doveroso sostegno economico per i soggetti "
            "effettivamente fragili non in condizioni di lavorare: penso ai pensionati in "
            "difficoltà, agli invalidi, a cui va aumentato in ogni modo il grado di tutela, "
            "e anche a chi privo di reddito ha figli minori di cui farsi carico."
        ),
        "topic_code": "13",
        **CLASS,
    },
    "108": {
        "commitment_id": "108",
        "commitment_title": "Incentivare in ogni modo l'occupazione femminile",
        "commitment_text": (
            "E visto che i progetti familiari vanno di pari passo con il lavoro, vogliamo "
            "incentivare in ogni modo l'occupazione femminile, premiando quelle aziende che "
            "adottano politiche che offrono soluzioni efficaci per conciliare i tempi "
            "casa-lavoro e sostenendo i comuni per garantire asili nido gratuiti e aperti "
            "fino all'orario di chiusura dei negozi e degli uffici."
        ),
        "topic_code": "20",
        "specificity": "medium",
        "commitment_type": "action",
        "holder_role": "government_coalition",
    },
    "109": {
        "commitment_id": "109",
        "commitment_title": "Recuperare la proposta originaria della missione navale Sophia",
        "commitment_text": (
            "è nostra intenzione recuperare la proposta originaria della missione navale "
            "Sophia dell'Unione europea, che nella terza fase, prevista e mai attuata, "
            "prevedeva proprio il blocco delle partenze dei barconi dal Nordafrica."
        ),
        "topic_code": "9",
        "specificity": "medium",
        "commitment_type": "action",
        "holder_role": "government_coalition",
    },
}

CLOSED = ["kept", "broken", "stalled"]
ALL_VERDICTS = ["kept", "partially_kept", "broken", "stalled", "in_progress"]


def case(case_id, kind, pledge, *, document, source_url, source_title, published_at,
         excerpt, retrieval, label, overlap, explanation, acceptable=(), unacceptable=None):
    row = {
        "case_id": case_id,
        "kind": kind,
        "overlap_type": overlap,
        "actor": ACTOR,
        "announcement_date": ANN,
        **P[pledge],
        "document": document,
        "source_url": source_url or "",
        "source_title": source_title,
        "published_at": published_at,
        "exact_excerpt": excerpt,
        "expected_retrieval": retrieval,
        "expected_label": label,
        "acceptable_verdicts": list(acceptable),
        "unacceptable_verdicts": list(unacceptable if unacceptable is not None else ALL_VERDICTS),
        "explanation": explanation,
    }
    return row


CASES = [
    case(
        "pos-autonomia-law86", "positive", "106",
        document="../legge_86_2024_autonomia.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg",
        source_title="Gazzetta Ufficiale — Legge 26 giugno 2024, n. 86",
        published_at="2024-06-26",
        excerpt="Disposizioni per l'attuazione dell'autonomia differenziata delle Regioni a statuto ordinario ai sensi dell'articolo 116, terzo comma, della Costituzione.",
        retrieval="relevant", label="supports", overlap="implementation",
        acceptable=("in_progress", "partially_kept"), unacceptable=CLOSED,
        explanation="Later framework law names and enacts the autonomia differenziata process. Supports follow-through, not completed regional autonomy.",
    ),
    case(
        "title-giudiziario-law114", "title_only", "104",
        document="../legge_114_2024_ordinamento.html",
        source_url="https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:2024-08-09;114",
        source_title="Gazzetta / Normattiva — Legge 9 agosto 2024, n. 114",
        published_at="2024-08-09",
        excerpt="Art. 4. Modifiche all'ordinamento giudiziario. All'ordinamento giudiziario, di cui al regio decreto 30 gennaio 1941, n. 12, sono apportate le seguenti modificazioni: tabella infradistrettuale; collegio per i provvedimenti di applicazione della misura della custodia cautelare in carcere.",
        retrieval="relevant", label="not_enough_info", overlap="title_only",
        acceptable=(),
        explanation="Art. 4 revises office tables and collegial pre-trial detention. No article addresses logiche correntizie or CSM factions. Title/instrument overlap only. Judge must abstain.",
    ),
    case(
        "neg-giudiziario-law86", "negative", "104",
        document="../legge_86_2024_autonomia.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg",
        source_title="Gazzetta Ufficiale — Legge 26 giugno 2024, n. 86",
        published_at="2024-06-26",
        excerpt="Disposizioni per l'attuazione dell'autonomia differenziata delle Regioni a statuto ordinario.",
        retrieval="irrelevant", label="not_enough_info", overlap="instrument_mismatch",
        explanation="Official later law, different policy. Must not become a judicial-reform candidate.",
    ),
    case(
        "neg-infrastrutture-tim-note", "negative", "101",
        document="../governo_nota_rete_tim_2024.html",
        source_url="https://www.governo.it/it/articolo/nota-di-palazzo-chigi-libera-del-governo-italiano-alla-vendita-della-rete-tim-al-fondo",
        source_title="Nota di Palazzo Chigi — vendita rete TIM a KKR",
        published_at="2024-01-17",
        excerpt="via libera del Governo italiano alla vendita della rete TIM al fondo infrastrutturale statunitense KKR",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Official same-topic follow-up authorises a private-fund sale. It is not evidence of public ownership of the networks and must not retrieve as fulfilment evidence.",
    ),
    case(
        "abstain-sophia-no-later-evidence", "abstain", "109",
        document=None, source_url="", source_title="", published_at=None, excerpt="",
        retrieval="irrelevant", label="not_enough_info", overlap="no_evidence",
        explanation="No later official evidence is supplied. Matcher must abstain.",
    ),
    case(
        "contradict-autonomia-corte192", "contradictory", "106",
        document="../corte_192_2024_autonomia.html",
        source_url="https://www.cortecostituzionale.it/scheda-pronuncia/2024/192",
        source_title="Corte costituzionale — Sentenza 192/2024",
        published_at="2024-12-03",
        excerpt="La Corte costituzionale dichiara l'illegittimita' costituzionale di alcune disposizioni della legge 26 giugno 2024, n. 86",
        retrieval="relevant", label="not_enough_info", overlap="contradictory",
        explanation="Official later judgment limits Law 86 but does not show the government abandoned the process. Not enough for supports or a closed refute.",
    ),
    case(
        "pos-carceri-law112", "positive", "103",
        document="../legge_112_2024_penitenziaria.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2024/08/09/24G00133/sg",
        source_title="Gazzetta Ufficiale — Legge 8 agosto 2024, n. 112",
        published_at="2024-08-08",
        excerpt="Conversione in legge, con modificazioni, del decreto-legge 4 luglio 2024, n. 92, recante misure urgenti in materia penitenziaria",
        retrieval="relevant", label="supports", overlap="implementation",
        acceptable=("in_progress",), unacceptable=CLOSED + ["partially_kept"],
        explanation="Later official conversion of the prison-emergency decree creates a commissario and prison-building programme. That is follow-through on piano carceri, not certainty-of-punishment completion.",
    ),
    case(
        "neg-carceri-law114", "negative", "103",
        document="../legge_114_2024_ordinamento.html",
        source_url="https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:2024-08-09;114",
        source_title="Legge 9 agosto 2024, n. 114",
        published_at="2024-08-09",
        excerpt="Modifiche all'ordinamento giudiziario ... tabella infradistrettuale",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Same justice topic, different instrument. Not piano carceri or certezza della pena.",
    ),
    case(
        "neg-carceri-law86", "negative", "103",
        document="../legge_86_2024_autonomia.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg",
        source_title="Legge 26 giugno 2024, n. 86",
        published_at="2024-06-26",
        excerpt="attuazione dell'autonomia differenziata",
        retrieval="irrelevant", label="not_enough_info", overlap="instrument_mismatch",
        explanation="Different policy area.",
    ),
    case(
        "same-102-tim", "negative", "102",
        document="../governo_nota_rete_tim_2024.html",
        source_url="https://www.governo.it/it/articolo/nota-di-palazzo-chigi-libera-del-governo-italiano-alla-vendita-della-rete-tim-al-fondo",
        source_title="Nota di Palazzo Chigi — rete TIM",
        published_at="2024-01-17",
        excerpt="vendita della rete TIM al fondo infrastrutturale statunitense KKR",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Infrastructure follow-up, not a safeguard clause on motorway or airport concessions.",
    ),
    case(
        "same-102-sky-alps", "negative", "102",
        document="../mit_sky_alps_2024.html",
        source_url="https://www.mit.gov.it/nfsmitgov/files/media/normativa/2024-07/REGISTRO%20DECRETI%20%28R%29.0000028.04-06-2024%20-%20Copia.pdf",
        source_title="Decreto MIT 4 giugno 2024 — OSP Sky Alps",
        published_at="2024-06-04",
        excerpt="prorogata fino al 31 ottobre 2024 la concessione in esclusiva alla Societa' di navigazione aerea SKY ALPS",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Official airport concession/OSP act. No clausola di salvaguardia of national economic interest.",
    ),
    case(
        "title-102-a24", "title_only", "102",
        document="../a24_reintegra_2024.html",
        source_url="https://www.gazzettaufficiale.it/atto/vediMenuHTML?atto.codiceRedazionale=T-240030&atto.dataPubblicazioneGazzetta=2024-02-28&tipoSerie=corte_costituzionale&tipoVigenza=originario",
        source_title="Gazzetta — concessione autostrade A24 e A25",
        published_at="2024-02-28",
        excerpt="reintegra di Strada dei Parchi spa nella concessione delle autostrade A24 e A25",
        retrieval="irrelevant", label="not_enough_info", overlap="title_only",
        explanation="Official concession language without the promised national-interest safeguard clause.",
    ),
    case(
        "same-105-riscossione", "negative", "105",
        document="../dlgs_110_2024_riscossione.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2024/08/07/24G00128/sg",
        source_title="Decreto legislativo 29 luglio 2024, n. 110",
        published_at="2024-07-29",
        excerpt="atto di contestazione all'agente della riscossione",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Tax-collection contestation procedure is not a change of Agenzia KPI from assessments to cash collected.",
    ),
    case(
        "same-105-concordato", "negative", "105",
        document="../dlgs_13_2024_accertamento.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2024/02/21/24G00026/sg",
        source_title="Decreto legislativo 12 febbraio 2024, n. 13",
        published_at="2024-02-12",
        excerpt="Disposizioni in materia di accertamento tributario e di concordato preventivo biennale.",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Same-topic tax administration reform. Does not recode Agenzia performance to amounts actually collected.",
    ),
    case(
        "abstain-105-no-criteria", "abstain", "105",
        document=None, source_url="", source_title="", published_at=None, excerpt="",
        retrieval="irrelevant", label="not_enough_info", overlap="no_evidence",
        explanation="No later official act that changes Agenzia evaluation criteria to cash collected is in the fixture set.",
    ),
    case(
        "pos-107-assegno-inclusione", "positive", "107",
        document="../legge_85_2023_assegno_inclusione.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2023/07/03/23G00087/sg",
        source_title="Gazzetta Ufficiale — Legge 3 luglio 2023, n. 85",
        published_at="2023-07-03",
        excerpt="E' istituito l'Assegno di inclusione, quale misura nazionale di contrasto alla poverta', alla fragilita' e all'esclusione sociale",
        retrieval="relevant", label="supports", overlap="implementation",
        acceptable=("in_progress", "partially_kept"), unacceptable=CLOSED,
        explanation="Later official inclusion allowance covers disabled, minors, and elderly without income. Partial follow-through on fragile-household support, not the whole pledge.",
    ),
    case(
        "neg-107-law86", "negative", "107",
        document="../legge_86_2024_autonomia.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg",
        source_title="Legge 26 giugno 2024, n. 86",
        published_at="2024-06-26",
        excerpt="autonomia differenziata delle Regioni",
        retrieval="irrelevant", label="not_enough_info", overlap="instrument_mismatch",
        explanation="Different policy area.",
    ),
    case(
        "pos-108-asili-nido", "positive", "108",
        document="../legge_197_2022_asili_nido.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2022/12/29/22G00211/sg",
        source_title="Gazzetta Ufficiale — Legge 29 dicembre 2022, n. 197",
        published_at="2022-12-29",
        excerpt="sono incrementate le risorse destinate ai comuni per il finanziamento di asili nido",
        retrieval="relevant", label="supports", overlap="implementation",
        acceptable=("in_progress", "partially_kept"), unacceptable=CLOSED,
        explanation="Budget law funds municipal nurseries. That is one limb of the female-employment pledge, not the whole workplace-policy package.",
    ),
    case(
        "neg-108-law114", "negative", "108",
        document="../legge_114_2024_ordinamento.html",
        source_url="https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:2024-08-09;114",
        source_title="Legge 9 agosto 2024, n. 114",
        published_at="2024-08-09",
        excerpt="Modifiche al codice penale, al codice di procedura penale, all'ordinamento giudiziario",
        retrieval="irrelevant", label="not_enough_info", overlap="instrument_mismatch",
        explanation="Different policy area.",
    ),
    case(
        "same-109-cutro", "negative", "109",
        document="../legge_50_2023_cutro.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2023/05/05/23G00058/sg",
        source_title="Gazzetta Ufficiale — Legge 5 maggio 2023, n. 50",
        published_at="2023-05-05",
        excerpt="disposizioni urgenti in materia di flussi di ingresso legale dei lavoratori stranieri e di prevenzione e contrasto all'immigrazione irregolare",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Official later migration act. It is not a revival of EU mission Sophia or its third-phase departure blockade.",
    ),
    case(
        "proc-104-calendar", "procedural", "104",
        document="../giustizia_calendario_2024.html",
        source_url="https://www.giustizia.it/giustizia/it/mg_2_4.page",
        source_title="Ministero della giustizia — calendario commissioni",
        published_at="2024-03-01",
        excerpt="Il Ministero della giustizia pubblica il calendario delle commissioni per il mese di marzo.",
        retrieval="irrelevant", label="not_enough_info", overlap="procedural",
        explanation="Official procedural calendar. No implementing provision.",
    ),
    case(
        "announce-106-cdm", "announcement", "106",
        document="../cdm_ddl_autonomia_2023.html",
        source_url="https://www.governo.it/it/articolo/comunicato-stampa-del-consiglio-dei-ministri-n-19/21687",
        source_title="Comunicato stampa del Consiglio dei Ministri n. 19",
        published_at="2023-02-02",
        excerpt="ha approvato un disegno di legge che reca disposizioni per l'attuazione dell'autonomia differenziata delle Regioni a statuto ordinario",
        retrieval="relevant", label="not_enough_info", overlap="announcement",
        explanation="Official announcement of a bill is not a promulgated implementing law. Retrieval may surface it; the judge must abstain.",
    ),
    case(
        "actor-108-esteri", "negative", "108",
        document="../esteri_visita_2024.html",
        source_url="https://www.esteri.it/it/sala_stampa/archivionotizie/comunicati/",
        source_title="Ministero degli Affari Esteri — visita del Presidente del Consiglio",
        published_at="2024-06-15",
        excerpt="Il Presidente del Consiglio Giorgia Meloni ha incontrato le autorita' del Paese ospite",
        retrieval="irrelevant", label="not_enough_info", overlap="actor_only",
        explanation="Official actor mention only. No female-employment or nursery instrument.",
    ),
    case(
        "date-106-legge42", "negative", "106",
        document="../legge_42_2009_autonomia.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2009/05/06/009G0058/sg",
        source_title="Legge 5 maggio 2009, n. 42",
        published_at="2009-05-05",
        excerpt="Delega al Governo in materia di federalismo fiscale, in attuazione dell'articolo 119 della Costituzione.",
        retrieval="irrelevant", label="not_enough_info", overlap="date_window",
        explanation="Earlier official autonomy-adjacent act is outside the post-announcement window.",
    ),
    case(
        "neg-carceri-sovraffollamento", "negative", "103",
        document="../giustizia_sovraffollamento_2024.html",
        source_url="https://www.giustizia.it/giustizia/it/mg_1_14.page",
        source_title="Ministero della giustizia — sovraffollamento strutture penitenziarie",
        published_at="2024-09-30",
        excerpt="dati sulla capienza regolamentare e sulla presenza media nelle strutture penitenziarie",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Official prison-estate statistics mention strutture penitenziarie and even edilizia penitenziaria while stating they do not approve a building programme. Alias without promulgation must not retrieve.",
    ),
    case(
        "neg-carceri-organigramma", "negative", "103",
        document="../giustizia_direzione_edilizia_2024.html",
        source_url="https://www.giustizia.it/giustizia/it/mg_12.page",
        source_title="Ministero della giustizia — organigramma edilizia penitenziaria",
        published_at="2024-04-01",
        excerpt="competenze in materia di edilizia penitenziaria e tiene l'elenco dei procedimenti di manutenzione ordinaria",
        retrieval="irrelevant", label="not_enough_info", overlap="procedural",
        explanation="Organizational notice names the edilizia penitenziaria office. Not an implementing prison-plan law.",
    ),
    case(
        "neg-carceri-polizia", "negative", "103",
        document="../giustizia_polizia_penitenziaria_2024.html",
        source_url="https://www.giustizia.it/giustizia/it/mg_1_8.page",
        source_title="Ministero della giustizia — concorso polizia penitenziaria",
        published_at="2024-05-15",
        excerpt="assunzione di personale del Corpo di polizia penitenziaria",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Same justice/prison administration topic. Staff hiring is not a piano carceri.",
    ),
    case(
        "neg-107-linee-guida", "negative", "107",
        document="../lavoro_inclusione_linee_guida_2024.html",
        source_url="https://www.lavoro.gov.it/temi-e-priorita/poverta-ed-esclusione-sociale",
        source_title="Ministero del lavoro — linee guida inclusione sociale",
        published_at="2024-03-12",
        excerpt="indicazioni operative per i servizi sociali territoriali a favore delle persone in condizione di fragilita'",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Generic social-inclusion guidance mentions fragility and names Assegno di inclusione only to say it is not instituted here.",
    ),
    case(
        "neg-107-adi-statistica", "negative", "107",
        document="../istat_adi_beneficiari_2024.html",
        source_url="https://www.istat.it/it/archivio/assegno-di-inclusione",
        source_title="Istat — nuclei percettori dell'Assegno di inclusione",
        published_at="2024-06-01",
        excerpt="numero di nuclei familiari percettori dell'Assegno di inclusione per regione",
        retrieval="irrelevant", label="not_enough_info", overlap="procedural",
        explanation="Official statistics about AdI beneficiaries. Alias without an implementing enactment must not retrieve.",
    ),
    case(
        "neg-107-assegno-unico", "negative", "107",
        document="../mef_assegno_unico_2023.html",
        source_url="https://www.mef.gov.it/ufficio-stampa/comunicati/2023/assegno-unico/",
        source_title="MEF — assegno unico e universale",
        published_at="2023-03-01",
        excerpt="erogazione dell'assegno unico e universale per i figli a carico",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Different cash benefit for all families with children. Not the AdI instrument and not limited to people unable to work.",
    ),
]


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "pledge-evidence-gold/v3",
        "notes": (
            "Official-source gold set for evidence relevance and conservative FEVER "
            "semantics. Not a political score."
        ),
        "cases": CASES,
    }
    path = ROOT / "manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(CASES)} cases to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
