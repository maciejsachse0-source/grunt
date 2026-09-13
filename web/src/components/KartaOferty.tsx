"use client";

/**
 * Karta dzialki. Sekcja 7.3 dokumentu.
 *
 * Kolejnosc sekcji odpowiada temu, co realnie rozstrzyga o decyzji:
 * najpierw ocena z jawna kompletnoscia, potem czerwone flagi, potem rozbicie
 * na filary, na koncu surowe dane z ogloszenia. Link do zrodla jest zawsze
 * widoczny, bo kierowanie ruchu do portalu to centralny argument obronny
 * z sekcji 8.2.
 */

import { useEffect, useState } from "react";
import type { OfertaSzczegoly } from "@/lib/api";
import {
  OPIS_STATUSU,
  OPIS_ZRODLA_RODZAJU,
  format,
  nazwaRegionu,
  nazwaRodzaju,
  nazwaSegmentu,
  pobierzOferte,
} from "@/lib/api";
import { ZapisOferty } from "./ZapisOferty";

const NAZWY_FILAROW: Record<string, string> = {
  planistyka: "Planistyka",
  lokalizacja: "Lokalizacja",
  infrastruktura: "Infrastruktura",
  fizyka: "Fizyka działki",
  ryzyka: "Ryzyka środowiskowe",
  rynek: "Rynek gminy",
};

export function KartaOferty({
  id,
  onZamknij,
  onZmianaZapisu,
}: {
  id: number;
  onZamknij: () => void;
  onZmianaZapisu?: () => void;
}) {
  // Stan zmieniamy wylacznie w callbackach obietnicy. React 19 nie pozwala
  // wolac setState synchronicznie w ciele efektu, bo to kaskaduje renderowanie.
  // Czyszczenie przy zmianie oferty zalatwia prop key w komponencie nadrzednym.
  const [stan, setStan] = useState<{ oferta?: OfertaSzczegoly; blad?: string }>({});

  useEffect(() => {
    let aktualne = true;
    pobierzOferte(id)
      .then((dane) => aktualne && setStan({ oferta: dane }))
      .catch((e) => aktualne && setStan({ blad: String(e) }));
    return () => {
      aktualne = false;
    };
  }, [id]);

  const { oferta, blad } = stan;

  if (blad) return <Panel onZamknij={onZamknij}>Nie udało się pobrać oferty: {blad}</Panel>;
  if (!oferta) return <Panel onZamknij={onZamknij}>Wczytywanie…</Panel>;

  const status = oferta.planistyka.status;
  const ceny = [oferta, ...oferta.duplikaty]
    .map((o) => o.cena_zl)
    .filter((cena): cena is number => typeof cena === "number" && cena > 0);
  const roznicaCen =
    ceny.length > 1 ? (Math.max(...ceny) - Math.min(...ceny)) / Math.min(...ceny) : null;

  return (
    <Panel onZamknij={onZamknij}>
      <h2 className="pr-8 text-base font-semibold leading-snug">{oferta.tytul ?? "Działka"}</h2>

      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-sm">
        <strong>{format.zl(oferta.cena_zl)}</strong>
        <span>{format.m2(oferta.powierzchnia_m2)}</span>
        {oferta.cena_m2 !== null && <span>{Math.round(oferta.cena_m2)} zł/m²</span>}
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
        {!oferta.rodzaj ? (
          <span title="ogłoszenie nie mówi, jaka to działka">rodzaj nieokreślony</span>
        ) : (
          <span>
            działka {nazwaRodzaju(oferta.rodzaj)}
            <span className="text-slate-400">
              {" "}
              ({OPIS_ZRODLA_RODZAJU[oferta.rodzaj_zrodlo ?? ""] ?? "źródło nieznane"})
            </span>
          </span>
        )}
        {oferta.region && (
          <>
            <span aria-hidden>·</span>
            <span>
              {nazwaRegionu(oferta.region)}
              {oferta.region.powiat ? `, ${oferta.region.powiat}` : ""}
              {oferta.region.zrodlo === "rcn" && (
                <span
                  className="text-slate-400"
                  title="gmina ustalona z najbliższej transakcji RCN, bo działki nie udało się dopasować"
                >
                  {" "}
                  (przybliżona)
                </span>
              )}
            </span>
          </>
        )}
      </div>

      {oferta.rynek && (
        <div className="szklo-lekkie mt-3 p-3 text-xs">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-slate-500">wobec rynku lokalnego</span>
            <strong
              className={
                oferta.rynek.odchylenie <= -0.1
                  ? "text-emerald-700 dark:text-emerald-400"
                  : oferta.rynek.odchylenie >= 0.1
                    ? "text-red-700 dark:text-red-400"
                    : ""
              }
            >
              {format.procentZeZnakiem(oferta.rynek.odchylenie)}
            </strong>
          </div>
          <p className="mt-1 text-slate-500">
            {Math.round(oferta.rynek.cena_zl_m2_norm)} zł/m² znormalizowane wobec mediany{" "}
            {Math.round(oferta.rynek.mediana_zl_m2)} zł/m² —{" "}
            {oferta.rynek.obszar ?? "obszar"} ({oferta.rynek.poziom}),{" "}
            {oferta.rynek.n} transakcji, {nazwaSegmentu(oferta.rynek.segment)}.
          </p>
          {oferta.rynek.segment === "*" && (
            <p className="mt-1 text-amber-700 dark:text-amber-400">
              Ogłoszenie nie podaje przeznaczenia działki, więc tłem jest cały rynek obszaru,
              od gruntów rolnych po budowlane. Traktuj tę liczbę orientacyjnie.
            </p>
          )}
        </div>
      )}

      <div className="szklo-lekkie mt-3 p-3">
        <ZapisOferty id={oferta.id} onZmiana={onZmianaZapisu} />
      </div>

      <section className="szklo-lekkie mt-4 p-4">
        {oferta.score === null ? (
          <p className="text-sm text-slate-500">
            Za mało danych, żeby policzyć ocenę. Kompletność {format.procent(oferta.kompletnosc)}.
            Zły wynik byłby gorszy niż jego brak.
          </p>
        ) : (
          <div className="flex items-baseline gap-3">
            <span className="bg-[linear-gradient(150deg,var(--akcent-jasny),var(--akcent))] bg-clip-text text-4xl font-semibold tabular-nums text-transparent">
              {oferta.score.toFixed(0)}
            </span>
            <div className="text-xs text-slate-500">
              <div>na 100 punktów potencjału</div>
              <div>kompletność danych {format.procent(oferta.kompletnosc)}</div>
            </div>
            {oferta.deal_score !== null && (
              <span className="ml-auto text-right text-sm">
                <span className="block text-xs text-slate-500">deal score</span>
                {oferta.deal_score > 0 ? "+" : ""}
                {format.liczba(oferta.deal_score, 2)}
              </span>
            )}
          </div>
        )}

        {oferta.gate && oferta.gate.aktywne.length > 0 && (
          <div className="mt-3 rounded-lg border border-rose-600/25 bg-rose-200/40 p-3 text-xs text-rose-700">
            <strong>Mnożnik dyskwalifikujący ×{oferta.gate.mnoznik.toFixed(2)}</strong>
            <ul className="mt-1 list-disc pl-4">
              {oferta.gate.aktywne.map((g) => (
                <li key={g.nazwa}>{g.powod}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {oferta.duplikaty.length > 0 && (
        <Sekcja tytul="Ta sama działka gdzie indziej">
          <ul className="space-y-2 text-xs">
            {oferta.duplikaty.map((duplikat) => (
              <li key={duplikat.id} className="szklo-lekkie p-3">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-slate-500">{duplikat.portal}</span>
                  <strong className="tabular-nums">{format.zl(duplikat.cena_zl)}</strong>
                </div>
                <a
                  href={duplikat.url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-0.5 block break-all text-slate-600 underline dark:text-slate-400"
                >
                  {duplikat.tytul ?? duplikat.url}
                </a>
                {/* Powod sklejenia jest widoczny, bo to ocena z progiem, a nie fakt. */}
                <p className="mt-1 text-slate-500">
                  {duplikat.pewnosc !== null
                    ? `pewność ${Math.round(duplikat.pewnosc * 100)}%, etap: ${duplikat.etap}`
                    : "połączone przez inną ofertę w tej samej grupie"}
                </p>
              </li>
            ))}
          </ul>
          {roznicaCen !== null && roznicaCen > 0.02 && (
            <p className="mt-2 text-xs text-amber-800 dark:text-amber-300">
              Rozrzut cen między portalami: {Math.round(roznicaCen * 100)}%. Sam w sobie jest
              sygnałem — warto sprawdzić, która oferta jest aktualna.
            </p>
          )}
        </Sekcja>
      )}

      {oferta.czerwone_flagi.length > 0 && (
        <Sekcja tytul="Czerwone flagi">
          <ul className="list-disc space-y-1 pl-4 text-sm text-amber-800 dark:text-amber-300">
            {oferta.czerwone_flagi.map((flaga, i) => (
              <li key={i}>{flaga}</li>
            ))}
          </ul>
        </Sekcja>
      )}

      <Sekcja tytul="Status planistyczny">
        <p className="text-sm">
          <span className="font-mono font-semibold">{status ?? "?"}</span>{" "}
          {OPIS_STATUSU[status ?? "?"]}
        </p>
        {oferta.planistyka.strefa && (
          <p className="mt-1 text-xs text-slate-500">
            strefa {oferta.planistyka.strefa}
            {oferta.planistyka.w_ouz === true && ", działka w Obszarze Uzupełnienia Zabudowy"}
            {oferta.planistyka.w_ouz === false && ", działka poza OUZ"}
          </p>
        )}
      </Sekcja>

      {oferta.filary && (
        <Sekcja tytul="Rozbicie na filary">
          <div className="space-y-1.5">
            {Object.entries(oferta.filary).map(([klucz, punkty]) => (
              <div key={klucz} className="flex items-center gap-2 text-xs">
                <span className="w-28 shrink-0 text-slate-500">
                  {NAZWY_FILAROW[klucz] ?? klucz}
                </span>
                {punkty === null ? (
                  <span className="text-slate-400">brak danych</span>
                ) : (
                  <>
                    <span className="h-2 flex-1 overflow-hidden rounded-full bg-slate-200/70 dark:bg-white/10">
                      <span
                        className="block h-full rounded-full bg-[var(--akcent)]"
                        style={{ width: `${Math.max(2, punkty)}%` }}
                      />
                    </span>
                    <span className="w-8 text-right tabular-nums">{punkty.toFixed(0)}</span>
                  </>
                )}
              </div>
            ))}
          </div>
        </Sekcja>
      )}

      <Sekcja tytul="Dane z warstw publicznych">
        <dl className="text-xs">
          <Pozycja etykieta="Koszt mediów" wartosc={format.zl(oferta.media_koszt_pln)} />
          <Pozycja
            etykieta="Front"
            wartosc={oferta.front_m ? `${format.liczba(oferta.front_m)} m` : "—"}
          />
          <Pozycja
            etykieta="Spadek terenu"
            wartosc={oferta.spadek_proc ? `${format.liczba(oferta.spadek_proc)}%` : "—"}
          />
          <Pozycja
            etykieta="Strefy powodziowe"
            wartosc={oferta.strefy_powodziowe.join(", ") || "brak"}
          />
          <Pozycja etykieta="Działka ewidencyjna" wartosc={oferta.dzialka.uldk_id ?? "—"} />
          <Pozycja
            etykieta="Pewność dopasowania"
            wartosc={oferta.dzialka.pewnosc_dopasowania ?? "—"}
          />
        </dl>
        {(oferta.dzialka.pewnosc_dopasowania === "low" ||
          oferta.dzialka.pewnosc_dopasowania === "none") && (
          <p className="mt-2 text-xs text-slate-500">
            Współrzędne z portalu są przybliżone, więc numeru działki nie da się wskazać
            jednoznacznie. Cechy geometryczne mogą dotyczyć sąsiedniej parceli.
          </p>
        )}
      </Sekcja>

      {oferta.historia_ceny.length > 1 && (
        <Sekcja tytul="Historia ceny">
          <ul className="text-xs">
            {oferta.historia_ceny.map((wpis, i) => (
              <li key={i} className="wiersz-danych">
                <span className="text-slate-500">{format.data(wpis.data)}</span>
                <span className="tabular-nums">{format.zl(wpis.cena_zl)}</span>
              </li>
            ))}
          </ul>
        </Sekcja>
      )}

      <a
        href={oferta.url}
        target="_blank"
        rel="noreferrer"
        className="przycisk-glowny mt-5 w-full justify-between"
      >
        <span>Otwórz ofertę na {oferta.portal}</span>
        <span aria-hidden className="text-base leading-none">
          →
        </span>
      </a>
      <p className="mt-2 text-center text-xs text-slate-400">
        Dane kontaktowe są dostępne wyłącznie w serwisie źródłowym.
      </p>
    </Panel>
  );
}

function Panel({ children, onZamknij }: { children: React.ReactNode; onZamknij: () => void }) {
  return (
    // max-h i overflow musza siedziec na tej samej osi, inaczej dluga karta
    // wylewa sie poza ekran zamiast sie przewijac. Zewnetrzny box trzyma
    // wysokosc i przycisk zamkniecia, wewnetrzny przewija tresc.
    <div className="szklo-mocne relative flex max-h-[80svh] flex-col max-lg:rounded-b-none lg:max-h-[calc(100vh-3rem)]">
      <span
        aria-hidden
        className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-slate-300 lg:hidden"
      />
      <button
        onClick={onZamknij}
        aria-label="zamknij"
        className="absolute right-3 top-3 z-10 grid h-8 w-8 place-items-center rounded-full border border-slate-200 bg-white text-slate-400 transition-colors hover:border-slate-900 hover:text-slate-900"
      >
        ✕
      </button>
      <div className="min-h-0 overflow-y-auto px-5 pb-5 pt-4 lg:pt-5">{children}</div>
    </div>
  );
}

function Sekcja({ tytul, children }: { tytul: string; children: React.ReactNode }) {
  return (
    <section className="mt-4">
      <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">{tytul}</h3>
      {children}
    </section>
  );
}

function Pozycja({ etykieta, wartosc }: { etykieta: string; wartosc: string }) {
  return (
    <div className="wiersz-danych">
      <dt className="text-slate-500">{etykieta}</dt>
      <dd className="text-right tabular-nums">{wartosc}</dd>
    </div>
  );
}
