// Città seguite da VeraPolitica: i capoluoghi di regione (Trento e Bolzano entrambi) e le città
// scelte dalla redazione per peso politico (rubrica «Città prioritarie»). Sono le uniche città
// selezionabili su Territorio, dentro la loro provincia. `istat` è il codice ISTAT del comune
// (lo stesso di `istat_code` nell'API), `center` è [longitudine, latitudine].
export const KEY_CITIES = [
  { istat: "007003", name: "Aosta", sigla: "AO", region: "02", capital: true, center: [7.3155, 45.737] },
  { istat: "001272", name: "Torino", sigla: "TO", region: "01", capital: true, center: [7.6869, 45.0703] },
  { istat: "015146", name: "Milano", sigla: "MI", region: "03", capital: true, center: [9.19, 45.4642] },
  { istat: "010025", name: "Genova", sigla: "GE", region: "07", capital: true, center: [8.9463, 44.4056] },
  { istat: "022205", name: "Trento", sigla: "TN", region: "04", capital: true, center: [11.1217, 46.0748] },
  { istat: "021008", name: "Bolzano", sigla: "BZ", region: "04", capital: true, center: [11.3548, 46.4983] },
  { istat: "027042", name: "Venezia", sigla: "VE", region: "05", capital: true, center: [12.3155, 45.4408] },
  { istat: "023091", name: "Verona", sigla: "VR", region: "05", capital: false, center: [10.9916, 45.4384] },
  { istat: "032006", name: "Trieste", sigla: "TS", region: "06", capital: true, center: [13.7768, 45.6495] },
  { istat: "037006", name: "Bologna", sigla: "BO", region: "08", capital: true, center: [11.3426, 44.4949] },
  { istat: "034027", name: "Parma", sigla: "PR", region: "08", capital: false, center: [10.3279, 44.8015] },
  { istat: "048017", name: "Firenze", sigla: "FI", region: "09", capital: true, center: [11.2558, 43.7696] },
  { istat: "054039", name: "Perugia", sigla: "PG", region: "10", capital: true, center: [12.3888, 43.1107] },
  { istat: "042002", name: "Ancona", sigla: "AN", region: "11", capital: true, center: [13.5189, 43.6158] },
  { istat: "058091", name: "Roma", sigla: "RM", region: "12", capital: true, center: [12.4964, 41.9028] },
  { istat: "066049", name: "L'Aquila", sigla: "AQ", region: "13", capital: true, center: [13.3995, 42.3498] },
  { istat: "070006", name: "Campobasso", sigla: "CB", region: "14", capital: true, center: [14.6559, 41.5603] },
  { istat: "063049", name: "Napoli", sigla: "NA", region: "15", capital: true, center: [14.2681, 40.8518] },
  { istat: "072006", name: "Bari", sigla: "BA", region: "16", capital: true, center: [16.8719, 41.1171] },
  { istat: "076063", name: "Potenza", sigla: "PZ", region: "17", capital: true, center: [15.8056, 40.6404] },
  { istat: "079023", name: "Catanzaro", sigla: "CZ", region: "18", capital: true, center: [16.5987, 38.9098] },
  { istat: "082053", name: "Palermo", sigla: "PA", region: "19", capital: true, center: [13.3615, 38.1157] },
  { istat: "092009", name: "Cagliari", sigla: "CA", region: "20", capital: true, center: [9.1217, 39.2238] },
];

export const citiesInProvince = (sigla) => KEY_CITIES.filter((city) => city.sigla === sigla);
export const citiesInRegion = (istat) => KEY_CITIES.filter((city) => city.region === istat);
export const keyCity = (istat) => KEY_CITIES.find((city) => city.istat === istat) || null;
