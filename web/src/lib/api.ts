/**
 * Klient API GRUNT-a. Jedyne miejsce, ktore wie, gdzie stoi backend.
 *
 * Typy odpowiadaja kontraktowi z sekcji 20 dokumentu koncepcyjnego. Nie sa
 * generowane z OpenAPI, bo przy tej liczbie endpointow narzut byloby wiekszy
 * niz zysk, ale ksztalt jest ten sam co w api/routers/listings.py.
 */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Token do endpointow z danymi uzytkownika (/api/saved, /api/filters). Pusty
 * lokalnie, bo backend bez API_WRITE_TOKEN o nic nie pyta. Jawny w paczce
 * przegladarki: co ten token chroni, a czego nie, opisuje grunt/api/auth.py.
 */
const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? "";

function naglowki(zJsonem = false): Record<string, string> {
  const h: Record<string, string> = {};
  if (zJsonem) h["Content-Type"] = "application/json";
  if (API_TOKEN) h["X-Grunt-Token"] = API_TOKEN;
  return h;
}

export type PlanStatus = "A" | "B" | "C" | "D" | "E" | "?" | null;

export interface Planistyka {
  status: PlanStatus;
  strefa: string | null;
  w_ouz: boolean | null;
}

export interface Dzialka {
  uldk_id: string | null;
  pewnosc_dopasowania: "high" | "medium" | "low" | "none" | null;
}

/** Pozycja oferty wobec mediany transakcyjnej jej rynku lokalnego. */
export interface PozycjaRynkowa {
  /** 0.18 znaczy: o 18% drozsza od mediany. Nigdy null wewnatrz obiektu. */
  odchylenie: number;
  mediana_zl_m2: number;
  cena_zl_m2_norm: number;
  /** Liczba transakcji, na ktorych stoi mediana. Bez tego liczba jest ozdoba. */
  n: number;
  poziom: "gmina" | "powiat" | "wojewodztwo";
  obszar: string | null;
  /** "*" znaczy: przeznaczenia oferty nie znamy, tlem jest caly rynek obszaru. */
  segment: string;
}

/** Cztery kubelki, ktorymi mysli kupujacy. Zrodlo w scoring/rodzaj.py. */
export type RodzajDzialki =
  | "mieszkaniowa"
  | "uslugowa"
  | "przemyslowa"
  | "lesna";

export const NAZWY_RODZAJOW: Record<RodzajDzialki, string> = {
  mieszkaniowa: "mieszkaniowa",
  uslugowa: "usługowa",
  przemyslowa: "przemysłowa",
  lesna: "leśna",
};

/** Skad wiemy, jaki to rodzaj. Pokazywane w podpowiedzi, nie zgadywane. */
export const OPIS_ZRODLA_RODZAJU: Record<string, string> = {
  plan_ogolny: "ze strefy planu ogólnego gminy",
  ogloszenie: "z treści ogłoszenia",
};

/** Gmina, w ktorej lezy dzialka. null znaczy: nie da sie jej ustalic. */
export interface Region {
  teryt_gmina: string;
  /** null, dopóki ULDK nie poda nazwy. Interfejs pokazuje wtedy kod TERYT. */
  gmina: string | null;
  powiat: string | null;
  /** "dzialka" = z dopasowanej działki ewidencyjnej, "rcn" = z najbliższej transakcji. */
  zrodlo: string | null;
}

export interface Oferta {
  id: number;
  portal: string;
  url: string;
  tytul: string | null;
  cena_zl: number | null;
  powierzchnia_m2: number | null;
  cena_m2: number | null;
  lat: number | null;
  lon: number | null;
  thumb_url: string | null;
  pierwszy_raz: string;
  planistyka: Planistyka;
  /** null znaczy "nie wiemy", a nie "żadna z czterech kategorii". */
  rodzaj?: RodzajDzialki | null;
  rodzaj_zrodlo?: string | null;
  /* Trzy pola ponizej sa NIEOBOWIAZKOWE, bo /api/listings ich dzis nie
     wysyla - nie ma ich ani w odpowiedzi, ani w schemacie backendu. Typ musi
     to mowic wprost, inaczej "region.gmina" wywala aplikacje na undefined,
     a straznik "=== null" tego nie lapie. Gdy backend zacznie je podawac,
     wystarczy zdjac znak zapytania. */
  region?: Region | null;
  media_koszt_pln: number | null;
  front_m: number | null;
  spadek_proc: number | null;
  strefy_powodziowe: string[];
  dzialka: Dzialka;
  score: number | null;
  deal_score: number | null;
  kompletnosc: number | null;
  czerwone_flagi: string[];
  /** Numer klastra duplikatow. null oznacza "nie znaleziono duplikatu". */
  klaster: number | null;
  /** null znaczy "nie ma z czym porownac", a nie "dokladnie w medianie". */
  rynek: PozycjaRynkowa | null;
}

export interface Duplikat {
  id: number;
  portal: string;
  url: string;
  tytul: string | null;
  cena_zl: number | null;
  powierzchnia_m2: number | null;
  pewnosc: number | null;
  etap: string | null;
  powody: string[];
}

export interface OfertaSzczegoly extends Oferta {
  filary: Record<string, number | null> | null;
  gate: {
    mnoznik: number;
    aktywne: { nazwa: string; mnoznik: number; powod: string }[];
  } | null;
  wzbogacenie: Record<string, unknown> | null;
  historia_ceny: { cena_zl: number; data: string }[];
  duplikaty: Duplikat[];
  z_ogloszenia: Record<string, unknown> | null;
}

export interface ListaOfert {
  total: number;
  limit: number;
  offset: number;
  sort: string;
  items: Oferta[];
}

export interface Kalibracja {
  /** O ile ceny ofertowe leza wyzej niz wycena transakcyjna, np. 0.24 to +24%. */
  spread: number;
  n: number;
  /** "pary" to wlasciwy pomiar, "oferty_vs_model" to szacunek zastepczy. */
  zrodlo: string;
  kiedy: string;
}

export interface Statystyki {
  oferty: number;
  ze_wspolrzednymi: number;
  wzbogacone: number;
  ocenione: number;
  transakcje_rcn: number;
  ostatni_scraping: string | null;
  kalibracja: Kalibracja | null;
}

export interface Filtry {
  /** Oferta bez rozpoznanego rodzaju nie przechodzi tego filtru. */
  rodzaj?: RodzajDzialki[];
  /** Kody TERYT: 7 znaków gmina, 4 powiat, 2 województwo. Dopasowanie po prefiksie. */
  teryt?: string[];
  price_min?: number;
  price_max?: number;
  area_min?: number;
  area_max?: number;
  price_per_m2_max?: number;
  status_planistyczny?: string[];
  media_koszt_max?: number;
  front_min?: number;
  exclude_flood?: boolean;
  score_min?: number;
  tylko_ocenione?: boolean;
  bez_duplikatow?: boolean;
  /** -0.1 znaczy: pokaz tylko oferty co najmniej 10% ponizej mediany rynku. */
  odchylenie_max?: number;
  portal?: string[];
}

export type Sortowanie =
  | "score"
  | "deal"
  | "cena"
  | "cena_m2"
  | "powierzchnia"
  | "najnowsze"
  | "wzgledem_rynku";

function queryString(
  filtry: Filtry,
  extra: Record<string, string | number> = {},
): string {
  const params = new URLSearchParams();
  for (const [klucz, wartosc] of Object.entries(filtry)) {
    if (
      wartosc === undefined ||
      wartosc === null ||
      wartosc === "" ||
      wartosc === false
    )
      continue;
    if (Array.isArray(wartosc)) {
      wartosc.forEach((v) => params.append(klucz, String(v)));
    } else {
      params.set(klucz, String(wartosc));
    }
  }
  for (const [klucz, wartosc] of Object.entries(extra))
    params.set(klucz, String(wartosc));
  return params.toString();
}

async function pobierz<T>(sciezka: string): Promise<T> {
  const odpowiedz = await fetch(`${API_URL}${sciezka}`, {
    cache: "no-store",
    headers: naglowki(),
  });
  if (!odpowiedz.ok) {
    throw new Error(`API ${odpowiedz.status}: ${sciezka}`);
  }
  return (await odpowiedz.json()) as T;
}

export function pobierzOferty(
  filtry: Filtry,
  sort: Sortowanie,
  limit = 50,
  offset = 0,
): Promise<ListaOfert> {
  return pobierz<ListaOfert>(
    `/api/listings?${queryString(filtry, { sort, limit, offset })}`,
  );
}

export function pobierzOferte(id: number): Promise<OfertaSzczegoly> {
  return pobierz<OfertaSzczegoly>(`/api/listings/${id}`);
}

export function pobierzGeojson(
  filtry: Filtry,
): Promise<GeoJSON.FeatureCollection> {
  return pobierz<GeoJSON.FeatureCollection>(
    `/api/listings/geojson?${queryString(filtry, { limit: 2000 })}`,
  );
}

export function nazwaRodzaju(rodzaj: string | null | undefined): string {
  if (rodzaj === null || rodzaj === undefined) return "nieokreślony";
  return NAZWY_RODZAJOW[rodzaj as RodzajDzialki] ?? rodzaj;
}

/** Nazwa gminy, a gdy jej nie znamy, sam kod TERYT. Nigdy zgadywana. */
export function nazwaRegionu(region: Region | null | undefined): string {
  if (region === null || region === undefined) return "—";
  return region.gmina ?? region.teryt_gmina;
}

export interface ObszarZOfertami {
  teryt: string;
  nazwa: string | null;
  powiat: string | null;
  oferty: number;
}

export interface Kategorie {
  poziom: "gmina" | "powiat";
  rodzaje: { rodzaj: RodzajDzialki; oferty: number }[];
  /** Ile ofert nie ma rozpoznanego rodzaju. Stan danych, nie kategoria. */
  bez_rodzaju: number;
  obszary: ObszarZOfertami[];
  bez_regionu: number;
}

export function pobierzKategorie(
  poziom: "gmina" | "powiat" = "powiat",
  minOfert = 1,
): Promise<Kategorie> {
  return pobierz<Kategorie>(
    `/api/listings/kategorie?poziom=${poziom}&min_ofert=${minOfert}`,
  );
}

/* ------------------------------------------------------------------ obrys */

export type PewnoscDopasowania = "high" | "medium" | "low" | null;

export interface ObrysDzialki {
  listing_id: number;
  punkt: { lat: number; lon: number } | null;
  pewnosc: PewnoscDopasowania;
  uldk_id: string | null;
  powierzchnia_ewid_m2?: number | null;
  bbox?: [number, number, number, number];
  obrys: GeoJSON.Feature | null;
}

/** Obrys dopasowanej dzialki. Brak dzialki to poprawna odpowiedz, nie blad. */
export function pobierzObrys(id: number): Promise<ObrysDzialki> {
  return pobierz<ObrysDzialki>(`/api/listings/${id}/obrys`);
}

export function pobierzStatystyki(): Promise<Statystyki> {
  return pobierz<Statystyki>("/api/stats");
}

/* ---------------------------------------------------------- ulubione i filtry */

export type StatusZapisu =
  "nowa" | "obserwuje" | "kontakt" | "odrzucona" | "kupiona";

export const STATUSY_ZAPISU: { wartosc: StatusZapisu; etykieta: string }[] = [
  { wartosc: "nowa", etykieta: "nowa" },
  { wartosc: "obserwuje", etykieta: "obserwuję" },
  { wartosc: "kontakt", etykieta: "kontakt" },
  { wartosc: "odrzucona", etykieta: "odrzucona" },
  { wartosc: "kupiona", etykieta: "kupiona" },
];

export interface ZapisanaOferta extends Oferta {
  status: StatusZapisu;
  note: string | null;
  tags: string[];
  zapisano: string;
  zmieniono: string;
  /** false znaczy, ze ogloszenie zniknelo z portalu, ale zapis zostaje. */
  aktywna: boolean;
  ocena: -1 | 0 | 1 | null;
}

export interface ZapisanyFiltr {
  id: number;
  name: string;
  filter: Filtry;
  alert_enabled: boolean;
  alert_channel: string | null;
  last_alert_at: string | null;
  wyslane: number;
}

async function wyslij<T>(
  sciezka: string,
  metoda: string,
  cialo?: unknown,
): Promise<T> {
  const odpowiedz = await fetch(`${API_URL}${sciezka}`, {
    method: metoda,
    headers: naglowki(Boolean(cialo)),
    body: cialo ? JSON.stringify(cialo) : undefined,
  });
  if (!odpowiedz.ok) {
    const tresc = await odpowiedz.text();
    throw new Error(`API ${odpowiedz.status}: ${tresc.slice(0, 200)}`);
  }
  return (await odpowiedz.json()) as T;
}

export function pobierzZapisane(status?: StatusZapisu): Promise<{
  total: number;
  items: ZapisanaOferta[];
}> {
  const q = status ? `?status=${status}` : "";
  return pobierz<{ total: number; items: ZapisanaOferta[] }>(`/api/saved${q}`);
}

export function zapiszOferte(
  id: number,
  dane: { status: StatusZapisu; note?: string | null; tags?: string[] },
): Promise<{ zapisano: boolean }> {
  return wyslij<{ zapisano: boolean }>(`/api/saved/${id}`, "PUT", dane);
}

export function usunZapis(id: number): Promise<{ usunieto: boolean }> {
  return wyslij<{ usunieto: boolean }>(`/api/saved/${id}`, "DELETE");
}

export function ocenOferte(
  id: number,
  verdict: -1 | 0 | 1,
): Promise<{ zapisano: boolean }> {
  return wyslij<{ zapisano: boolean }>(`/api/saved/${id}/ocena`, "POST", {
    verdict,
  });
}

export function pobierzFiltry(): Promise<{
  total: number;
  items: ZapisanyFiltr[];
}> {
  return pobierz<{ total: number; items: ZapisanyFiltr[] }>("/api/filters");
}

export function zapiszFiltr(
  name: string,
  filter: Filtry,
  alert_enabled: boolean,
): Promise<{ id: number }> {
  return wyslij<{ id: number }>("/api/filters", "POST", {
    name,
    filter,
    alert_enabled,
  });
}

export function zmienFiltr(
  id: number,
  zmiana: { alert_enabled?: boolean; name?: string },
): Promise<{ zmieniono: boolean }> {
  return wyslij<{ zmieniono: boolean }>(`/api/filters/${id}`, "PATCH", zmiana);
}

export function usunFiltr(id: number): Promise<{ usunieto: boolean }> {
  return wyslij<{ usunieto: boolean }>(`/api/filters/${id}`, "DELETE");
}

/** Formatowanie liczb tak, jak czyta je czlowiek, a nie tak, jak trzyma je baza. */
export const format = {
  zl(wartosc: number | null | undefined): string {
    if (wartosc === null || wartosc === undefined) return "—";
    return `${wartosc.toLocaleString("pl-PL")} zł`;
  },
  m2(wartosc: number | null | undefined): string {
    return wartosc === null || wartosc === undefined
      ? "—"
      : `${wartosc.toLocaleString("pl-PL")} m²`;
  },
  liczba(wartosc: number | null | undefined, miejsca = 1): string {
    return wartosc === null || wartosc === undefined
      ? "—"
      : wartosc.toFixed(miejsca);
  },
  procent(wartosc: number | null | undefined): string {
    return wartosc === null || wartosc === undefined
      ? "—"
      : `${Math.round(wartosc * 100)}%`;
  },
  /** Ze znakiem, bo "+12%" i "-12%" to dwie rozne informacje, a "12%" zadna. */
  procentZeZnakiem(wartosc: number | null | undefined, miejsca = 0): string {
    if (wartosc === null || wartosc === undefined) return "—";
    const procenty = wartosc * 100;
    return `${procenty > 0 ? "+" : ""}${procenty.toFixed(miejsca)}%`;
  },
  data(wartosc: string | null | undefined): string {
    if (!wartosc) return "—";
    return new Date(wartosc).toLocaleDateString("pl-PL");
  },
  /** Data z godzina. Przy harmonogramie sama data nie mowi nic uzytecznego. */
  dataGodzina(wartosc: string | null | undefined): string {
    if (!wartosc) return "—";
    return new Date(wartosc).toLocaleString("pl-PL", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  },
  /** "3,5 h", "2 dni". Interwaly i odstepy czyta sie w jednostce, nie w godzinach. */
  czas(godziny: number | null | undefined): string {
    if (godziny === null || godziny === undefined) return "—";
    if (godziny >= 24) {
      const dni = godziny / 24;
      return `${dni.toLocaleString("pl-PL")} ${dni === 1 ? "dzień" : "dni"}`;
    }
    if (godziny < 1) return `${Math.round(godziny * 60)} min`;
    return `${godziny.toLocaleString("pl-PL")} h`;
  },
};

/** Opisy statusow planistycznych, zgodne z sekcja 5.3.3 dokumentu. */
export const OPIS_STATUSU: Record<string, string> = {
  A: "MPZP z przeznaczeniem budowlanym",
  B: "plan ogólny, działka w OUZ",
  C: "ważna decyzja o warunkach zabudowy",
  D: "poza OUZ, bez MPZP — brak ścieżki do zabudowy",
  E: "brak planu ogólnego, ścieżka WZ otwarta",
  "?": "brak danych planistycznych",
};

/* ------------------------------------------------------- ceny w regionach */

export type PoziomObszaru = "gmina" | "powiat" | "wojewodztwo";

export interface CenaRegionu {
  teryt: string;
  /** null, gdy ULDK nie rozpoznal gminy. Interfejs pokazuje wtedy kod TERYT. */
  nazwa: string | null;
  powiat: string | null;
  n: number;
  /** Mediana ceny za m2 znormalizowanej do 1000 m2 i zindeksowanej na dzis. */
  mediana: number;
  p25: number;
  p75: number;
  /** Mediana cen faktycznie zaplaconych, bez korekt. Do porownania z powyzsza. */
  mediana_surowa: number;
  dynamika: number | null;
  oferty: number;
  okres: string;
}

export interface SegmentRynku {
  segment: string;
  obszary: number;
  transakcje: number;
  mediana_median: string;
}

export const NAZWY_SEGMENTOW: Record<string, string> = {
  "*": "wszystkie razem",
  mieszkaniowa_jednorodzinna: "zabudowa jednorodzinna",
  mieszkaniowa_wielorodzinna: "zabudowa wielorodzinna",
  uslugowa_produkcyjna: "usługowa i produkcyjna",
  rekreacyjna: "rekreacyjna",
  rolna: "rolna",
  lesna: "leśna",
  droga: "drogi",
  budowlana_wz: "budowlana z WZ",
  nieokreslona: "RCN nie podał przeznaczenia",
  nieokreslona_rolna: "bez przeznaczenia, ewidencja rolna",
  nieokreslona_zurbanizowana: "bez przeznaczenia, ewidencja zurbanizowana",
};

export function nazwaSegmentu(segment: string): string {
  return NAZWY_SEGMENTOW[segment] ?? segment;
}

export function pobierzCenyRegionow(params: {
  poziom: PoziomObszaru;
  segment: string;
  min_n: number;
  sort: string;
  /** TERYT obszaru nadrzednego: "2215" zwroci gminy powiatu wejherowskiego. */
  rodzic?: string;
}): Promise<{ total: number; items: CenaRegionu[] }> {
  const q = new URLSearchParams({
    poziom: params.poziom,
    segment: params.segment,
    min_n: String(params.min_n),
    sort: params.sort,
    limit: "200",
  });
  if (params.rodzic) q.set("rodzic", params.rodzic);
  return pobierz<{ total: number; items: CenaRegionu[] }>(`/api/market?${q}`);
}

export function pobierzSegmentyRynku(
  poziom: PoziomObszaru,
): Promise<{ items: SegmentRynku[] }> {
  return pobierz<{ items: SegmentRynku[] }>(
    `/api/market/segmenty?poziom=${poziom}`,
  );
}

export interface PunktHistorii {
  okres: string;
  etykieta: string;
  mediana: number;
  p25: number;
  p75: number;
  n: number;
  /** false = kwartal niepelny, RCN publikuje z opoznieniem. */
  pelny: boolean;
}

export interface HistoriaCen {
  poziom: PoziomObszaru;
  teryt: string;
  nazwa: string | null;
  segment: string;
  punkty: PunktHistorii[];
  transakcje: number;
  kwartaly_pominiete: number;
  /**
   * Trend Theil-Sena z pelnych kwartalow. null, gdy szereg jest za cienki,
   * zeby trend byl mierzalny (mniej niz szesc kwartalow, mniej niz dwa lata
   * okna albo mediana ponizej dziesieciu transakcji na kwartal).
   */
  zmiana_roczna: number | null;
  koniec_danych: string | null;
}

export function pobierzHistorieCen(params: {
  poziom: PoziomObszaru;
  teryt: string;
  segment: string;
}): Promise<HistoriaCen> {
  const q = new URLSearchParams(params);
  return pobierz<HistoriaCen>(`/api/market/historia?${q}`);
}

// ------------------------------------------------------- metodologia

/**
 * Prog, powyzej ktorego oferta jest wyrozniana jako okazja.
 *
 * Ta sama liczba stoi w scoring/valuation.py jako PROG_OKAZJI i jest
 * wystawiana przez /api/metodologia. Zakladka "jak to liczymy" pokazuje
 * obie obok siebie, wiec rozjechanie sie tych wartosci jest widoczne
 * na ekranie, a nie ukryte w kodzie.
 */
export const PROG_OKAZJI = 1.5;

export interface FilarOpis {
  klucz: string;
  nazwa: string;
  waga_detaliczny: number | null;
  waga_deweloper: number | null;
  funkcja: string | null;
  wejscie: string | null;
  zrodla: string[];
  jak: string | null;
  /** Na ilu ocenionych ofertach filar naprawde dostal dane. */
  ma_dane: number;
  z_ilu: number;
}

export interface GateOpis {
  nazwa: string;
  mnoznik: number;
  powod: string;
  aktywny_w_ofertach: number;
}

export interface StatusPlanistyczny {
  status: string;
  opis: string;
  mnoznik_min: number;
  mnoznik_max: number;
  punkty: number | null;
  ofert: number;
}

export interface ZrodloDanych {
  klucz: string;
  nazwa: string;
  co_daje: string;
  url: string;
  uwaga: string;
  /** null dla zrodel odpytywanych wsadowo, poza petla wzbogacania. */
  udanych_odpytan: number | null;
  bledow: number;
  wierszy_w_bazie: number | null;
}

export interface ZadanieOpis {
  kind: string;
  opis: string;
  co_ile_godzin: number;
  ostatnie: string | null;
  status: string | null;
  wynik: Record<string, unknown> | null;
}

/** Jeden wpis z tabeli calibrations: spread albo beta1 dla segmentu. */
export interface KalibracjaWpis {
  segment: string | null;
  wartosc: number | null;
  n: number | null;
  zrodlo: string | null;
  kiedy: string | null;
}

export interface Metodologia {
  score: {
    wzor: string;
    wyjasnienie_wzoru: string;
    coverage_min: number;
    regula_coverage: string;
    profil_domyslny: string;
    filary: FilarOpis[];
    punkty_statusu: Record<string, number>;
    gates: GateOpis[];
    wyjasnienie_gates: string;
    statusy_planistyczne: StatusPlanistyczny[];
    rozklad: {
      ocenionych: number;
      z_wynikiem: number;
      bez_wyniku: number;
      mediana: number | null;
      min: number | null;
      max: number | null;
      mediana_kompletnosci: number | null;
      ponizej_progu_kompletnosci: number;
      ostatnie_liczenie: string | null;
    };
  };
  wycena: {
    model: string;
    opis: string;
    normalizacja: string;
    parametry: Record<string, number>;
    wyjasnienie_sigma: string;
    beta1: KalibracjaWpis[];
    wyjasnienie_beta1: string;
  };
  deal: {
    wzor: string;
    opis: string;
    spread: KalibracjaWpis | null;
    wyjasnienie_spreadu: string;
    prog_okazji: number;
    wyjasnienie_progu: string;
    rozklad: {
      z_deal_score: number;
      p25: number | null;
      mediana: number | null;
      p75: number | null;
      min: number | null;
      max: number | null;
      powyzej_progu: number;
    };
  };
  rynek: {
    opis: string;
    wybor_poziomu: string;
    progi: Record<string, number>;
    filtr_transakcji: string;
    trend: string;
    stan: Record<string, number>;
  };
  zrodla: ZrodloDanych[];
  zadania: ZadanieOpis[];
  dane: Record<string, number>;
  prywatnosc: {
    zasada: string;
    co_sprawdzamy: string;
    dozwolone: {
      table_name: string;
      column_name: string;
      uzasadnienie: string;
    }[];
    naruszenia: { table_name: string; column_name: string }[];
  };
}

export function pobierzMetodologie(): Promise<Metodologia> {
  return pobierz<Metodologia>("/api/metodologia");
}

/* --------------------------------------------------------- harmonogram pobran */

/** Statystyki jednego portalu z jednego przebiegu, prosto z RunStats.as_dict(). */
export interface PrzebiegPortalu {
  portal: string;
  stron_wynikow: number;
  ofert_na_listingu: number;
  nowe: number;
  zmienione: number;
  bez_zmian: number;
  zalegle_detale: number;
  pobrane_detale: number;
  detale_z_bledem: number;
  wygaszone: number;
  zablokowane_przez_robots: number;
  bledy: string[];
}

export interface PortalHarmonogram {
  portal: string;
  adres: string | null;
  wlaczony: boolean;
  /** Wpisany w PORTALS_ENABLED, ale nie ma dla niego kodu. Cisza to nie awaria. */
  bez_adaptera: boolean;
  odstep_s: number | null;
  adresow_startowych: number;
  maks_stron_na_adres: number;
  ofert_w_bazie: number;
  aktywnych: number;
  nowych_24h: number;
  nowych_7d: number;
  ostatnia_nowa: string | null;
  ostatnio_widziany: string | null;
  /** null znaczy: portal nie brał udziału w ostatnim udanym przebiegu. */
  ostatni_przebieg: PrzebiegPortalu | null;
}

export interface ZadanieHarmonogram {
  kind: string;
  opis: string;
  co_ile_godzin: number;
  payload: Record<string, unknown>;
  ostatnie: string | null;
  nastepne: string | null;
  za_ile_godzin: number | null;
  wymagalne: boolean;
  w_kolejce: boolean;
}

export interface Harmonogram {
  teraz: string;
  worker: {
    opis: string;
    jak_uruchomic: string;
    ostatnie_zadanie: string | null;
    cisza_minut: number | null;
    prog_ciszy_minut: number;
    /** Domysl z ciszy w kolejce, nie odczyt z procesu. */
    prawdopodobnie_chodzi: boolean;
    kolejka: {
      czeka: number;
      w_trakcie: number;
      zakonczone: number;
      nieudane: number;
    };
    najblizsze_zadanie: string | null;
    odstep_petli_s: number;
  };
  scrape: {
    co_ile_godzin: number;
    dlaczego_tyle: string;
    ostatni: string | null;
    nastepny: string | null;
    za_ile_godzin: number | null;
    w_kolejce: boolean;
    strategia: string;
    przebiegi: {
      id: number;
      status: string;
      start: string | null;
      koniec: string | null;
      trwalo_minut: number | null;
      prob: number;
      blad: string | null;
      portale: PrzebiegPortalu[];
    }[];
  };
  portale: PortalHarmonogram[];
  zadania: ZadanieHarmonogram[];
  zasady: {
    odstep_s: number;
    maks_stron_na_przebieg: number;
    user_agent: string;
    region_teryt: string;
    wygaszenie_po_dniach: number;
    backoff_minut: number[];
    maks_prob: number;
    punkty: string[];
  };
}

export function pobierzHarmonogram(): Promise<Harmonogram> {
  return pobierz<Harmonogram>("/api/harmonogram");
}
