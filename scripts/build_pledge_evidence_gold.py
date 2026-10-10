"""Write the expanded official-evidence gold manifest. Never publishes."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "pledge_evidence" / "gold"

ACTOR = "Giorgia Meloni"
ANN = "2022-10-25"
MELONI_MANDATE = {"mandate_start": "2022-10-22", "mandate_end": "2027-10-12"}
CLASS = {
    "specificity": "high",
    "commitment_type": "action",
    "holder_role": "government_coalition",
    "actor": ACTOR,
    "announcement_date": ANN,
    **MELONI_MANDATE,
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
        "actor": ACTOR,
        "announcement_date": ANN,
        **MELONI_MANDATE,
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
        "actor": ACTOR,
        "announcement_date": ANN,
        **MELONI_MANDATE,
    },
    "201": {
        "commitment_id": "201",
        "commitment_title": "Realizzare il Ponte sullo Stretto tra le infrastrutture strategiche",
        "commitment_text": (
            "Realizzeremo il Ponte sullo Stretto di Messina, opera necessaria tra le "
            "infrastrutture strategiche nazionali."
        ),
        "topic_code": "10",
        "specificity": "high",
        "commitment_type": "action",
        "holder_role": "government_coalition",
        "actor": "Matteo Salvini",
        "announcement_date": "2022-10-25",
        **MELONI_MANDATE,
    },
    "202": {
        "commitment_id": "202",
        "commitment_title": "Rafforzare la missione navale italiana nel Mediterraneo",
        "commitment_text": (
            "Rafforzeremo la missione navale italiana nel Mediterraneo nel quadro della "
            "NATO e della difesa europea."
        ),
        "topic_code": "16",
        "specificity": "medium",
        "commitment_type": "action",
        "holder_role": "government_coalition",
        "actor": "Antonio Tajani",
        "announcement_date": "2022-10-25",
        **MELONI_MANDATE,
    },
    "203": {
        "commitment_id": "203",
        "commitment_title": "Introdurre il reddito di cittadinanza",
        "commitment_text": (
            "Introdurremo il reddito di cittadinanza come misura nazionale di contrasto "
            "alla poverta' per i nuclei in difficolta'."
        ),
        "topic_code": "13",
        "specificity": "high",
        "commitment_type": "action",
        "holder_role": "government_coalition",
        "actor": "Giuseppe Conte",
        "announcement_date": "2018-06-05",
        "mandate_start": "2018-06-01",
        "mandate_end": "2021-02-13",
    },
    "204": {
        "commitment_id": "204",
        "commitment_title": "Attuare il Piano nazionale di ripresa e resilienza",
        "commitment_text": (
            "Attueremo il Piano nazionale di ripresa e resilienza per modernizzare la "
            "pubblica amministrazione e gli investimenti pubblici."
        ),
        "topic_code": "20",
        "specificity": "medium",
        "commitment_type": "action",
        "holder_role": "government_coalition",
        "actor": "Mario Draghi",
        "announcement_date": "2021-02-17",
        "mandate_start": "2021-02-13",
        "mandate_end": "2022-10-22",
    },
    "205": {
        "commitment_id": "205",
        "commitment_title": "Introdurre la certificazione verde COVID-19",
        "commitment_text": (
            "Introdurremo la certificazione verde COVID-19, il green pass, per l'accesso "
            "ai luoghi di lavoro e ai servizi."
        ),
        "topic_code": "3",
        "specificity": "high",
        "commitment_type": "action",
        "holder_role": "government_coalition",
        "actor": "Roberto Speranza",
        "announcement_date": "2021-07-22",
        "mandate_start": "2019-09-05",
        "mandate_end": "2022-10-22",
    },
    "206": {
        "commitment_id": "206",
        "commitment_title": "Ridurre le liste di attesa del Servizio sanitario nazionale",
        "commitment_text": (
            "Rafforzeremo il Servizio sanitario nazionale e ridurremo le liste di attesa "
            "per le prestazioni ambulatoriali."
        ),
        "topic_code": "3",
        "specificity": "medium",
        "commitment_type": "action",
        "holder_role": "government_coalition",
        "actor": "Orazio Schillaci",
        "announcement_date": "2022-10-25",
        **MELONI_MANDATE,
    },
    "207": {
        "commitment_id": "207",
        "commitment_title": "Ridurre il cuneo fiscale per i lavoratori dipendenti",
        "commitment_text": (
            "Ridurremo il cuneo fiscale per i lavoratori dipendenti con una misura "
            "strutturale in legge di bilancio."
        ),
        "topic_code": "1",
        "specificity": "medium",
        "commitment_type": "action",
        "holder_role": "government_coalition",
        "actor": "Giancarlo Giorgetti",
        "announcement_date": "2022-10-25",
        **MELONI_MANDATE,
    },
    "208": {
        "commitment_id": "208",
        "commitment_title": "Difendere il reddito di cittadinanza",
        "commitment_text": (
            "Difenderemo il reddito di cittadinanza e rafforzeremo il contrasto alla "
            "poverta' per chi non e' in condizioni di lavorare."
        ),
        "topic_code": "13",
        "specificity": "medium",
        "commitment_type": "action",
        "holder_role": "opposition",
        "actor": "Elly Schlein",
        "announcement_date": "2023-03-12",
        "mandate_start": None,
        "mandate_end": None,
    },
    "209": {
        "commitment_id": "209",
        "commitment_title": "Istituire l'assegno unico e universale per i figli",
        "commitment_text": (
            "Istituiremo l'assegno unico e universale per i figli a carico, in sostituzione "
            "delle misure frammentate di sostegno alla natalita'."
        ),
        "topic_code": "13",
        "specificity": "high",
        "commitment_type": "action",
        "holder_role": "government_coalition",
        "actor": "Mario Draghi",
        "announcement_date": "2021-02-17",
        "mandate_start": "2021-02-13",
        "mandate_end": "2022-10-22",
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
    case(
        "pos-salvini-ponte", "positive", "201",
        document="../legge_ponte_stretto_2023.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2023/04/22/23G00047/sg",
        source_title="Gazzetta Ufficiale — disposizioni per il Ponte sullo Stretto",
        published_at="2023-04-21",
        excerpt="disposizioni per la realizzazione del Ponte sullo Stretto di Messina tra le infrastrutture strategiche nazionali",
        retrieval="relevant", label="supports", overlap="implementation",
        acceptable=("in_progress", "partially_kept"), unacceptable=CLOSED,
        explanation="Later official act names the Strait bridge among national strategic infrastructures. Follow-through on the pledged work, not completion of the crossing.",
    ),
    case(
        "same-salvini-sky-alps", "negative", "201",
        document="../mit_sky_alps_2024.html",
        source_url="https://www.mit.gov.it/nfsmitgov/files/media/normativa/2024-07/REGISTRO%20DECRETI%20%28R%29.0000028.04-06-2024%20-%20Copia.pdf",
        source_title="Decreto MIT 4 giugno 2024 — OSP Sky Alps",
        published_at="2024-06-04",
        excerpt="prorogata fino al 31 ottobre 2024 la concessione in esclusiva alla Societa' di navigazione aerea SKY ALPS",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Official transport concession. Not the Strait-bridge instrument.",
    ),
    case(
        "announce-salvini-ponte", "announcement", "201",
        document="../cdm_ponte_stretto_2023.html",
        source_url="https://www.governo.it/it/articolo/comunicato-stampa-del-consiglio-dei-ministri-n-27/21801",
        source_title="Comunicato stampa del Consiglio dei Ministri — Ponte sullo Stretto",
        published_at="2023-03-16",
        excerpt="ha approvato un disegno di legge che reca disposizioni per il Ponte sullo Stretto di Messina tra le infrastrutture strategiche",
        retrieval="relevant", label="not_enough_info", overlap="announcement",
        explanation="Official bill announcement names the instrument. Retrieval may surface it; the judge must abstain without promulgation.",
    ),
    case(
        "actor-salvini-esteri", "negative", "201",
        document="../esteri_visita_2024.html",
        source_url="https://www.esteri.it/it/sala_stampa/archivionotizie/comunicati/",
        source_title="Ministero degli Affari Esteri — visita",
        published_at="2024-06-15",
        excerpt="Il Presidente del Consiglio Giorgia Meloni ha incontrato le autorita' del Paese ospite",
        retrieval="irrelevant", label="not_enough_info", overlap="actor_only",
        explanation="Official foreign-visit note. No Strait-bridge instrument.",
    ),
    case(
        "stat-salvini-istat-traffico", "negative", "201",
        document="../istat_traffico_stretto_2024.html",
        source_url="https://www.istat.it/it/archivio/traffico-marittimo-stretto",
        source_title="Istat — traffico marittimo sullo Stretto",
        published_at="2024-05-02",
        excerpt="passeggeri e veicoli imbarcati sui collegamenti marittimi dello Stretto di Messina",
        retrieval="irrelevant", label="not_enough_info", overlap="procedural",
        explanation="Official ferry-traffic statistics. Not an implementing bridge act.",
    ),
    case(
        "pos-tajani-missione-navale", "positive", "202",
        document="../legge_missione_navale_2023.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2023/07/15/23G00102/sg",
        source_title="Gazzetta Ufficiale — proroga della missione navale nel Mediterraneo",
        published_at="2023-07-14",
        excerpt="proroga della missione navale italiana nel Mediterraneo nel quadro della NATO",
        retrieval="relevant", label="supports", overlap="implementation",
        acceptable=("in_progress",), unacceptable=CLOSED,
        explanation="Later official authorization continues the pledged naval mission. Open follow-through, not a closed defence outcome.",
    ),
    case(
        "same-tajani-cutro", "negative", "202",
        document="../legge_50_2023_cutro.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2023/05/05/23G00058/sg",
        source_title="Gazzetta Ufficiale — Legge 5 maggio 2023, n. 50",
        published_at="2023-05-05",
        excerpt="disposizioni urgenti in materia di flussi di ingresso legale dei lavoratori stranieri",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Official migration act. Not a naval-mission authorization.",
    ),
    case(
        "date-tajani-post-mandate", "negative", "202",
        document="../difesa_missione_navale_2028.html",
        source_url="https://www.difesa.it/smd/missione-navale-mediterraneo-2028",
        source_title="Stato Maggiore della Difesa — missione navale 2028",
        published_at="2028-01-20",
        excerpt="autorizzazione della missione navale italiana nel Mediterraneo per l'anno 2028",
        retrieval="irrelevant", label="not_enough_info", overlap="date_window",
        explanation="Official later mission act falls after the recorded mandate end.",
    ),
    case(
        "proc-tajani-senato", "procedural", "202",
        document="../senato_calendario_2024.html",
        source_url="https://www.senato.it/leg/19/BGT/Schede/Calendario/index.html",
        source_title="Senato della Repubblica — calendario dei lavori",
        published_at="2024-03-04",
        excerpt="Il Senato pubblica il calendario delle commissioni per la settimana.",
        retrieval="irrelevant", label="not_enough_info", overlap="procedural",
        explanation="Official parliamentary calendar. No mission authorization.",
    ),
    case(
        "pos-conte-rdc", "positive", "203",
        document="../legge_26_2019_rdc.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2019/03/29/19G00034/sg",
        source_title="Gazzetta Ufficiale — Legge 28 marzo 2019, n. 26",
        published_at="2019-03-28",
        excerpt="E' istituito il reddito di cittadinanza quale misura nazionale di contrasto alla poverta'",
        retrieval="relevant", label="supports", overlap="implementation",
        acceptable=("in_progress", "partially_kept", "kept"), unacceptable=["broken", "stalled"],
        explanation="Promulgated law institutes the pledged income-support instrument. Frozen retrieval may miss it if the phrase is not a known instrument.",
    ),
    case(
        "date-conte-post-mandate-adi", "negative", "203",
        document="../legge_85_2023_assegno_inclusione.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2023/07/03/23G00087/sg",
        source_title="Gazzetta Ufficiale — Legge 3 luglio 2023, n. 85",
        published_at="2023-07-03",
        excerpt="E' istituito l'Assegno di inclusione, quale misura nazionale di contrasto alla poverta'",
        retrieval="irrelevant", label="not_enough_info", overlap="date_window",
        explanation="Later replacement measure is outside Conte's mandate window.",
    ),
    case(
        "announce-conte-rdc", "announcement", "203",
        document="../cdm_rdc_2018.html",
        source_url="https://www.governo.it/it/articolo/comunicato-stampa-del-consiglio-dei-ministri-n-22/10340",
        source_title="Comunicato stampa del Consiglio dei Ministri — reddito di cittadinanza",
        published_at="2018-09-27",
        excerpt="ha approvato un disegno di legge che istituisce il reddito di cittadinanza",
        retrieval="irrelevant", label="not_enough_info", overlap="announcement",
        explanation="Bill announcement without a known frozen instrument phrase. Must not retrieve as implementation.",
    ),
    case(
        "pos-draghi-pnrr", "positive", "204",
        document="../dl_77_2021_pnrr.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2021/05/31/21G00087/sg",
        source_title="Gazzetta Ufficiale — Decreto-legge 31 maggio 2021, n. 77",
        published_at="2021-05-31",
        excerpt="Governance del Piano nazionale di ripresa e resilienza e prime misure di rafforzamento delle strutture amministrative",
        retrieval="relevant", label="supports", overlap="implementation",
        acceptable=("in_progress",), unacceptable=CLOSED,
        explanation="Official PNRR governance decree. Frozen retrieval may miss the unnamed instrument.",
    ),
    case(
        "date-draghi-post-mandate-law86", "negative", "204",
        document="../legge_86_2024_autonomia.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg",
        source_title="Legge 26 giugno 2024, n. 86",
        published_at="2024-06-26",
        excerpt="attuazione dell'autonomia differenziata",
        retrieval="irrelevant", label="not_enough_info", overlap="date_window",
        explanation="Later autonomy law is outside the Draghi mandate and is a different instrument.",
    ),
    case(
        "pos-speranza-greenpass", "positive", "205",
        document="../dl_105_2021_greenpass.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2021/07/23/21G00117/sg",
        source_title="Gazzetta Ufficiale — Decreto-legge 23 luglio 2021, n. 105",
        published_at="2021-07-23",
        excerpt="estende l'obbligo della certificazione verde COVID-19, il green pass, per l'accesso ai servizi",
        retrieval="relevant", label="supports", overlap="implementation",
        acceptable=("in_progress", "kept"), unacceptable=["broken", "stalled"],
        explanation="Promulgated decree introduces the pledged green-pass access rule. Frozen retrieval may miss the unnamed instrument.",
    ),
    case(
        "actor-speranza-salute", "negative", "205",
        document="../salute_visita_2021.html",
        source_url="https://www.salute.gov.it/portale/news/p3_2_1.jsp",
        source_title="Ministero della salute — visita istituzionale",
        published_at="2021-09-10",
        excerpt="Il Ministro della salute Roberto Speranza ha incontrato i direttori generali delle aziende sanitarie",
        retrieval="irrelevant", label="not_enough_info", overlap="actor_only",
        explanation="Official actor mention only. No green-pass instrument.",
    ),
    case(
        "court-speranza-corte", "contradictory", "205",
        document="../corte_greenpass_2022.html",
        source_url="https://www.cortecostituzionale.it/scheda-pronuncia/2022/15",
        source_title="Corte costituzionale — limiti alla certificazione verde",
        published_at="2022-02-10",
        excerpt="La Corte costituzionale dichiara l'illegittimita' costituzionale di alcune disposizioni sulla certificazione verde COVID-19",
        retrieval="irrelevant", label="not_enough_info", overlap="contradictory",
        explanation="Official later judgment limits the green-pass regime. Without a frozen instrument phrase it must not retrieve; the judge would abstain even if retrieved.",
    ),
    case(
        "pos-schillaci-liste", "positive", "206",
        document="../dl_73_2024_liste_attesa.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2024/06/07/24G00095/sg",
        source_title="Gazzetta Ufficiale — Decreto-legge 7 giugno 2024, n. 73",
        published_at="2024-06-07",
        excerpt="misure urgenti per la riduzione delle liste di attesa delle prestazioni sanitarie",
        retrieval="relevant", label="supports", overlap="implementation",
        acceptable=("in_progress",), unacceptable=CLOSED,
        explanation="Official waiting-list decree. Frozen retrieval may miss the unnamed instrument.",
    ),
    case(
        "date-schillaci-pre-mandate", "negative", "206",
        document="../dl_105_2021_greenpass.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2021/07/23/21G00117/sg",
        source_title="Decreto-legge 23 luglio 2021, n. 105",
        published_at="2021-07-23",
        excerpt="certificazione verde COVID-19, il green pass",
        retrieval="irrelevant", label="not_enough_info", overlap="date_window",
        explanation="Earlier public-health decree is outside Schillaci's post-announcement window.",
    ),
    case(
        "stat-schillaci-liste", "negative", "206",
        document="../istat_liste_attesa_2024.html",
        source_url="https://www.istat.it/it/archivio/liste-attesa-sanitarie",
        source_title="Istat — tempi di attesa delle prestazioni ambulatoriali",
        published_at="2024-09-12",
        excerpt="tempi mediani di attesa per visite specialistiche e diagnostica per regione",
        retrieval="irrelevant", label="not_enough_info", overlap="procedural",
        explanation="Official waiting-time statistics. Not an implementing decree.",
    ),
    case(
        "proc-schillaci-circolare", "procedural", "206",
        document="../salute_circolare_liste_2024.html",
        source_url="https://www.salute.gov.it/portale/news/circolare-liste-attesa",
        source_title="Ministero della salute — circolare alle regioni",
        published_at="2024-04-03",
        excerpt="indicazioni operative alle regioni per il monitoraggio delle liste di attesa",
        retrieval="irrelevant", label="not_enough_info", overlap="procedural",
        explanation="Ministry circular. Not a promulgated waiting-list act.",
    ),
    case(
        "pos-giorgetti-cuneo", "positive", "207",
        document="../legge_213_2023_cuneo.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2023/12/30/23G00223/sg",
        source_title="Gazzetta Ufficiale — Legge 30 dicembre 2023, n. 213",
        published_at="2023-12-30",
        excerpt="e' ridotto il cuneo fiscale per i lavoratori dipendenti",
        retrieval="relevant", label="supports", overlap="implementation",
        acceptable=("in_progress", "partially_kept"), unacceptable=CLOSED,
        explanation="Budget law reduces the labour tax wedge. Frozen retrieval may miss the unnamed instrument.",
    ),
    case(
        "same-giorgetti-concordato", "negative", "207",
        document="../dlgs_13_2024_accertamento.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2024/02/21/24G00026/sg",
        source_title="Decreto legislativo 12 febbraio 2024, n. 13",
        published_at="2024-02-12",
        excerpt="Disposizioni in materia di accertamento tributario e di concordato preventivo biennale.",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Same-topic tax administration reform. Not a cuneo-fiscale cut.",
    ),
    case(
        "same-schlein-law85", "negative", "208",
        document="../legge_85_2023_assegno_inclusione.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2023/07/03/23G00087/sg",
        source_title="Gazzetta Ufficiale — Legge 3 luglio 2023, n. 85",
        published_at="2023-07-03",
        excerpt="E' istituito l'Assegno di inclusione, quale misura nazionale di contrasto alla poverta'",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Later government replacement of citizenship income is not follow-through by an opposition holder.",
    ),
    case(
        "abstain-schlein-no-office", "abstain", "208",
        document=None, source_url="", source_title="", published_at=None, excerpt="",
        retrieval="irrelevant", label="not_enough_info", overlap="no_evidence",
        explanation="No later official act attributable to this opposition holder is supplied.",
    ),
    case(
        "pos-draghi-assegno-unico", "positive", "209",
        document="../dlgs_230_2021_assegno_unico.html",
        source_url="https://www.gazzettaufficiale.it/eli/id/2021/12/30/21G00252/sg",
        source_title="Gazzetta Ufficiale — Decreto legislativo 29 dicembre 2021, n. 230",
        published_at="2021-12-29",
        excerpt="E' istituito l'assegno unico e universale per i figli a carico",
        retrieval="relevant", label="supports", overlap="implementation",
        acceptable=("in_progress", "kept"), unacceptable=["broken", "stalled"],
        explanation="Official legislative decree institutes the pledged child allowance. Frozen retrieval may miss the unnamed instrument.",
    ),
    case(
        "proc-104-camera", "procedural", "104",
        document="../camera_calendario_2024.html",
        source_url="https://www.camera.it/leg19/210",
        source_title="Camera dei deputati — calendario dei lavori",
        published_at="2024-03-05",
        excerpt="La Camera dei deputati pubblica il calendario dell'Assemblea per la settimana.",
        retrieval="irrelevant", label="not_enough_info", overlap="procedural",
        explanation="Official Chamber calendar. No judicial-organisation instrument.",
    ),
    case(
        "same-109-interno-hotspot", "negative", "109",
        document="../interno_hotspot_2024.html",
        source_url="https://www.interno.gov.it/it/notizie/hotspot-lampedusa",
        source_title="Ministero dell'interno — aggiornamento hotspot",
        published_at="2024-04-18",
        excerpt="aggiornamento sulla capienza dell'hotspot di Lampedusa e sui trasferimenti",
        retrieval="irrelevant", label="not_enough_info", overlap="same_topic",
        explanation="Official hotspot operations note. Not a revival of mission Sophia.",
    ),
    case(
        "same-108-istruzione-asili", "negative", "108",
        document="../istruzione_circolare_asili_2024.html",
        source_url="https://www.istruzione.it/circolari/asili-nido-2024",
        source_title="Ministero dell'istruzione — circolare asili nido",
        published_at="2024-01-15",
        excerpt="indicazioni alle istituzioni scolastiche per i progetti di asili nido in convenzione",
        retrieval="relevant", label="not_enough_info", overlap="title_only",
        explanation="School-year circular names asili nido. Retrieval may surface the instrument phrase; the judge must abstain because the circular does not fund free municipal nurseries.",
    ),
    case(
        "announce-106-quirinale", "announcement", "106",
        document="../quirinale_promulga_86_2024.html",
        source_url="https://www.quirinale.it/elementi/comunicati/legge-86-2024",
        source_title="Quirinale — promulgazione della legge 86/2024",
        published_at="2024-06-26",
        excerpt="Il Presidente della Repubblica promulga la legge recante disposizioni per l'attuazione dell'autonomia differenziata",
        retrieval="relevant", label="supports", overlap="implementation",
        acceptable=("in_progress",), unacceptable=CLOSED,
        explanation="Official promulgation notice of Law 86 names the autonomia differenziata instrument.",
    ),
]


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "pledge-evidence-gold/v4",
        "notes": (
            "Official-source gold set for evidence relevance and conservative FEVER "
            "semantics. Multi-actor, multi-topic, multi-domain. Not a political score."
        ),
        "cases": CASES,
    }
    path = ROOT / "manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(CASES)} cases to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
