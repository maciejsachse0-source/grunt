"use client";

/**
 * Glowny ekran aplikacji: filtry, lista, mapa i karta oferty.
 *
 * Paginacja jest serwerowa (sekcja 4.2 dokumentu), bo lista docelowo urosnie
 * do kilku tysiecy ofert, a przegladarka nie ma powodu ich wszystkich trzymac.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { flushSync } from "react-dom";
import {
  Filtry,
  ListaOfert,
  Sortowanie,
  Statystyki,
  ZapisanaOferta,
  format,
  pobierzGeojson,
  pobierzOferty,
  pobierzStatystyki,
  pobierzZapisane,
} from "@/lib/api";
import { PanelFiltrow } from "@/components/Filtry";
import { TabelaOfert } from "@/components/TabelaOfert";
import { Mapa } from "@/components/Mapa";
import { CenyRegionow } from "@/components/CenyRegionow";
import { Metodologia } from "@/components/Metodologia";
import { Harmonogram } from "@/components/Harmonogram";
import { KartaOferty } from "@/components/KartaOferty";

const NA_STRONE = 50;

// Zakladki w kolejnosci czytania: najpierw oferty, potem to, co o nich mowi
// system (ceny, metoda), na koncu to, co mowi o samym systemie (rytm pobran).
const ZAKLADKI = ["wszystkie", "zapisane", "ceny", "metoda", "pobieranie"] as const;
type Widok = (typeof ZAKLADKI)[number];

const ETYKIETY: Record<Widok, string> = {
  wszystkie: "wszystkie oferty",
  zapisane: "zapisane",
  ceny: "ceny w regionach",
  metoda: "jak to liczymy",
  pobieranie: "kiedy pobieramy",
};

export default function Strona() {
  const [filtry, setFiltry] = useState<Filtry>({});
  const [sort, setSort] = useState<Sortowanie>("score");
  const [strona, setStrona] = useState(0);
  // Wynik trzymamy razem z kluczem zapytania. Dzieki temu "ladowanie" jest
  // wyliczane, a nie ustawiane recznie w efekcie (React 19 tego zabrania),
  // a przy zmianie filtrow stara lista zostaje na ekranie przygaszona,
  // zamiast migac pustym miejscem.
  const [wynik, setWynik] = useState<{
    klucz: string;
    lista: ListaOfert;
    geojson: GeoJSON.FeatureCollection;
  } | null>(null);
  const [blad, setBlad] = useState<{ klucz: string; tresc: string } | null>(
    null,
  );
  const [statystyki, setStatystyki] = useState<Statystyki | null>(null);
  const [wybrana, setWybrana] = useState<number | null>(null);
  // Zapisane sa osobnym widokiem, nie filtrem listy: to inne pytanie
  // ("co obserwuje") niz filtry ("czego szukam").
  const [widok, setWidok] = useState<Widok>("wszystkie");
  const [zapisane, setZapisane] = useState<ZapisanaOferta[]>([]);

  // Zmiana zakladki idzie przez View Transitions, zeby pomaranczowe
  // wypelnienie PRZEJECHALO miedzy guzikami zamiast zgasnac na jednym
  // i zapalic sie na drugim. Regula ::view-transition-* jest w globals.css.
  const zmienWidok = useCallback((nazwa: Widok) => {
    const start = (
      document as Document & {
        startViewTransition?: (aktualizacja: () => void) => unknown;
      }
    ).startViewTransition;

    // Przegladarka bez View Transitions albo uzytkownik, ktory poprosil system
    // o mniej ruchu, dostaje zmiane natychmiastowa. To brak ozdoby, nie blad.
    const mniejRuchu = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (typeof start !== "function" || mniejRuchu) {
      setWidok(nazwa);
      return;
    }

    // flushSync jest tu konieczny: startViewTransition robi zrzut nowego stanu
    // zaraz po powrocie z tego wywolania zwrotnego, a zwykly setState Reacta
    // jest wsadowy i zdazylby sie jeszcze nie wykonac.
    start.call(document, () => flushSync(() => setWidok(nazwa)));
  }, []);

  const odswiezZapisane = useCallback(() => {
    pobierzZapisane()
      .then((dane) => setZapisane(dane.items))
      .catch(() => setZapisane([]));
  }, []);

  useEffect(odswiezZapisane, [odswiezZapisane]);

  useEffect(() => {
    pobierzStatystyki()
      .then(setStatystyki)
      .catch(() => setStatystyki(null));
  }, []);

  const klucz = useMemo(
    () => JSON.stringify({ filtry, sort, strona }),
    [filtry, sort, strona],
  );

  useEffect(() => {
    let aktualne = true;

    Promise.all([
      pobierzOferty(filtry, sort, NA_STRONE, strona * NA_STRONE),
      pobierzGeojson(filtry),
    ])
      .then(([oferty, mapa]) => {
        if (aktualne) setWynik({ klucz, lista: oferty, geojson: mapa });
      })
      .catch((e) => {
        if (aktualne) setBlad({ klucz, tresc: String(e) });
      });

    return () => {
      aktualne = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [klucz]);

  const lista = wynik?.lista ?? null;
  const geojson = wynik?.geojson ?? null;
  const ladowanie = wynik?.klucz !== klucz && blad?.klucz !== klucz;

  const zmienFiltry = useCallback((nowe: Filtry) => {
    setFiltry(nowe);
    setStrona(0);
  }, []);

  const stron = lista ? Math.ceil(lista.total / NA_STRONE) : 0;

  return (
    <main className="mx-auto flex w-full max-w-[1700px] flex-col gap-5 p-4 sm:p-6">
      <header className="szklo flex flex-wrap items-center justify-between gap-4 px-5 py-4">
        <div className="flex items-center gap-3">
          {/* Znacznik marki: kropla swiatla zamiast logotypu, ktorego nie ma */}
          <span
            aria-hidden
            className="h-10 w-10 shrink-0 rounded-md bg-[var(--akcent)]"
          />
          <div>
            <h1 className="text-xl font-semibold tracking-tight">GRUNT</h1>
            <p className="text-xs text-slate-500">
              wyszukiwanie i ocena potencjału działek, województwo pomorskie
            </p>
          </div>
        </div>
        {statystyki && (
          <dl className="flex flex-wrap gap-2 text-xs text-slate-500">
            <Licznik etykieta="ofert" wartosc={statystyki.oferty} />
            <Licznik etykieta="wzbogaconych" wartosc={statystyki.wzbogacone} />
            <Licznik etykieta="ocenionych" wartosc={statystyki.ocenione} />
            <Licznik
              etykieta="transakcji RCN"
              wartosc={statystyki.transakcje_rcn}
            />
          </dl>
        )}
      </header>

      <nav className="flex flex-wrap gap-2 text-sm">
        {ZAKLADKI.map((nazwa) => (
          <button
            key={nazwa}
            onClick={() => zmienWidok(nazwa)}
            className={`zakladka ${widok === nazwa ? "zakladka-aktywna" : ""}`}
          >
            {nazwa === "zapisane"
              ? `zapisane (${zapisane.length})`
              : ETYKIETY[nazwa]}
          </button>
        ))}
      </nav>

      {blad?.klucz === klucz && (
        <div className="rounded-lg border border-rose-600/25 bg-rose-200/40 p-4 text-sm text-rose-700">
          Nie udało się pobrać danych z API: {blad.tresc}
          <br />
          <span className="text-xs">
            Sprawdź, czy backend działa:{" "}
            <code>uv run uvicorn grunt.api.main:app --reload</code>
          </span>
        </div>
      )}

      {widok === "ceny" && <CenyRegionow />}
      {widok === "metoda" && <Metodologia />}
      {widok === "pobieranie" && <Harmonogram />}

      {(widok === "wszystkie" || widok === "zapisane") && (
        <div className="flex flex-col gap-4 lg:flex-row">
          <PanelFiltrow
            filtry={filtry}
            onChange={zmienFiltry}
            liczbaWynikow={lista?.total ?? 0}
          />

          <div className="flex min-w-0 flex-1 flex-col gap-4">
            <div className="h-[340px] shrink-0">
              <Mapa
                geojson={geojson}
                wybrana={wybrana}
                onWybierz={setWybrana}
              />
            </div>

            {widok === "zapisane" && zapisane.length === 0 && (
              <p className="szklo p-6 text-center text-sm text-slate-500">
                Nic jeszcze nie obserwujesz. Otwórz kartę oferty i kliknij
                „Obserwuj tę ofertę”.
              </p>
            )}

            <TabelaOfert
              oferty={widok === "zapisane" ? zapisane : (lista?.items ?? [])}
              sort={sort}
              onSort={(nowy) => {
                setSort(nowy);
                setStrona(0);
              }}
              wybrana={wybrana}
              onWybierz={setWybrana}
              ladowanie={widok === "zapisane" ? false : ladowanie}
            />

            {widok === "wszystkie" && stron > 1 && (
              <div className="flex items-center justify-between gap-3 text-sm">
                <button
                  disabled={strona === 0}
                  onClick={() => setStrona((s) => s - 1)}
                  className="przycisk"
                >
                  poprzednia
                </button>
                <span className="text-xs text-slate-500">
                  strona {strona + 1} z {stron} ·{" "}
                  {lista?.total.toLocaleString("pl-PL")} ofert
                </span>
                <button
                  disabled={strona + 1 >= stron}
                  onClick={() => setStrona((s) => s + 1)}
                  className="przycisk"
                >
                  następna
                </button>
              </div>
            )}
          </div>

          {wybrana !== null && (
            // Ponizej lg karta jest dolnym arkuszem przyklejonym do krawedzi ekranu.
            // W ukladzie kolumnowym montowalaby sie pod cala tabela, wiec klikniecie
            // wiersza na telefonie nie dawaloby zadnej widocznej reakcji.
            <div className="fixed inset-x-0 bottom-0 z-40 w-full shrink-0 lg:sticky lg:inset-x-auto lg:bottom-auto lg:top-6 lg:z-auto lg:w-96">
              {/* key wymusza przemontowanie przy zmianie oferty, wiec karta nie
                pokazuje przez chwile danych poprzedniej dzialki */}
              <KartaOferty
                key={wybrana}
                id={wybrana}
                onZamknij={() => setWybrana(null)}
                onZmianaZapisu={odswiezZapisane}
              />
            </div>
          )}
        </div>
      )}

      <footer className="szklo px-5 py-4 text-xs leading-relaxed text-slate-500">
        Dane publiczne: RCN, EGiB, plany ogólne gmin (GUGiK), strefy powodziowe
        (ISOK), uzbrojenie (KIUT), wysokość (NMT). Oferty pochodzą z portali i
        linkują do źródła.
        {statystyki?.ostatni_scraping && (
          <> Ostatni scraping: {format.data(statystyki.ostatni_scraping)}.</>
        )}
        {statystyki?.kalibracja ? (
          <>
            {" "}
            Deal score porównuje cenę z wyceną podniesioną o zmierzony spread{" "}
            {(statystyki.kalibracja.spread * 100).toFixed(0)}% (n=
            {statystyki.kalibracja.n}
            {statystyki.kalibracja.zrodlo === "pary"
              ? ", pary oferta-transakcja"
              : ", szacunek zastępczy z wycen"}
            ).
          </>
        ) : (
          <>
            {" "}
            Deal score jest nieskalibrowany: porównuje cenę ofertową wprost z
            wyceną transakcyjną, więc wychodzi systematycznie ujemny.
          </>
        )}
      </footer>
    </main>
  );
}

function Licznik({ etykieta, wartosc }: { etykieta: string; wartosc: number }) {
  return (
    <div className="licznik text-right">
      <dt className="etykieta">{etykieta}</dt>
      <dd className="text-sm font-medium tabular-nums text-slate-900 dark:text-slate-100">
        {wartosc.toLocaleString("pl-PL")}
      </dd>
    </div>
  );
}
