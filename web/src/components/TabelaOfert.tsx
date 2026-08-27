"use client";

/**
 * Lista ofert. Kolumny z sekcji 7.1 dokumentu.
 *
 * Dwie decyzje warte odnotowania:
 *
 * 1. Oferta bez score'u pokazuje myslnik, nie zero. Sekcja 5.3.9: brak wyniku
 *    to informacja, a zero sugerowaloby, ze dzialka jest zla.
 * 2. Kompletnosc danych stoi obok score'u, a nie w szczegolach. Uzytkownik ma
 *    od razu widziec, na ilu danych opiera sie ocena.
 * 3. Kolumna "vs rynek" porownuje cene znormalizowana oferty z mediana
 *    TRANSAKCYJNA jej rynku lokalnego. Myslnik znaczy "nie ma z czym porownac",
 *    a nie "tyle samo co rynek". Liczba transakcji stojacych za mediana jest
 *    w podpowiedzi, bo mediana z 12 transakcji to co innego niz z 600.
 */

import { useMemo } from "react";
import type { CSSProperties } from "react";
import type { Oferta, PozycjaRynkowa, Sortowanie } from "@/lib/api";
import {
  OPIS_ZRODLA_RODZAJU,
  PROG_OKAZJI,
  format,
  nazwaRegionu,
  nazwaRodzaju,
  nazwaSegmentu,
} from "@/lib/api";

interface Props {
  oferty: Oferta[];
  sort: Sortowanie;
  onSort: (sort: Sortowanie) => void;
  wybrana: number | null;
  onWybierz: (id: number) => void;
  ladowanie: boolean;
}

const KOLUMNY: {
  klucz: Sortowanie | null;
  etykieta: string;
  szerokosc?: string;
}[] = [
  { klucz: "score", etykieta: "Score" },
  { klucz: "deal", etykieta: "Deal" },
  { klucz: null, etykieta: "Plan" },
  { klucz: null, etykieta: "Rodzaj i gmina" },
  { klucz: "powierzchnia", etykieta: "Pow." },
  { klucz: "cena", etykieta: "Cena" },
  { klucz: "cena_m2", etykieta: "zł/m²" },
  { klucz: "wzgledem_rynku", etykieta: "vs rynek" },
  { klucz: null, etykieta: "Media" },
  { klucz: null, etykieta: "Ryzyka" },
  { klucz: "najnowsze", etykieta: "Dodano" },
];

export function TabelaOfert({
  oferty,
  sort,
  onSort,
  wybrana,
  onWybierz,
  ladowanie,
}: Props) {
  // Animacja CSS gra przy montowaniu wezla. Wiersze sa kluczowane po id oferty,
  // wiec przy samym przesortowaniu React przestawia te same wezly i kaskada by
  // nie zagrala. Klucz na <tbody> zbudowany z listy identyfikatorow wymusza
  // przemontowanie zawsze wtedy, gdy zmienil sie ZESTAW albo KOLEJNOSC ofert,
  // i tylko wtedy: klikniecie wiersza zmienia "wybrana", nie oferty, wiec
  // podswietlenie nie odpala animacji od nowa.
  const pokolenie = useMemo(
    () => oferty.map((oferta) => oferta.id).join("-"),
    [oferty],
  );

  if (!ladowanie && oferty.length === 0) {
    return (
      <div className="szklo border-dashed p-10 text-center text-sm text-slate-500">
        Żadna oferta nie spełnia tych warunków.
      </div>
    );
  }

  return (
    <div className="szklo overflow-hidden">
      <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] text-sm">
        <thead className="tabela-naglowek text-xs uppercase tracking-wide text-slate-500">
          <tr>
            {KOLUMNY.map((kolumna) => (
              <th
                key={kolumna.etykieta}
                className="etykieta px-4 py-3 text-left"
              >
                {kolumna.klucz ? (
                  <button
                    onClick={() => onSort(kolumna.klucz!)}
                    className={`transition-colors hover:text-slate-900 dark:hover:text-slate-100 ${
                      sort === kolumna.klucz
                        ? "text-slate-900 underline decoration-[var(--akcent)] decoration-2 underline-offset-4"
                        : ""
                    }`}
                  >
                    {kolumna.etykieta}
                  </button>
                ) : (
                  kolumna.etykieta
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody key={pokolenie} className={ladowanie ? "opacity-50" : ""}>
          {oferty.map((oferta, indeks) => (
            <tr
              key={oferta.id}
              onClick={() => onWybierz(oferta.id)}
              // --i niesie numer wiersza do opoznienia animacji. Liczenie
              // opoznienia w CSS, a nie tutaj, zeby caly rytm kaskady dalo sie
              // przestawic jedna liczba w arkuszu.
              style={{ "--i": indeks } as CSSProperties}
              className={`wiersz wiersz-wejscie cursor-pointer ${
                wybrana === oferta.id ? "wiersz-wybrany" : ""
              }`}
            >
              <td className="px-4 py-2.5">
                <Score
                  wartosc={oferta.score}
                  kompletnosc={oferta.kompletnosc}
                />
              </td>
              <td className="px-4 py-2.5 tabular-nums">
                {oferta.deal_score === null ? (
                  <span className="text-slate-400">—</span>
                ) : (
                  <span
                    className={
                      oferta.deal_score >= PROG_OKAZJI
                        ? "font-semibold text-emerald-600"
                        : ""
                    }
                    title={`okazja od ${PROG_OKAZJI}: cena o tyle odchylen ponizej wyceny`}
                  >
                    {oferta.deal_score > 0 ? "+" : ""}
                    {format.liczba(oferta.deal_score, 1)}
                  </span>
                )}
              </td>
              <td className="px-4 py-2.5">
                <StatusPlanu
                  status={oferta.planistyka.status}
                  wOuz={oferta.planistyka.w_ouz}
                />
              </td>
              <td className="px-4 py-2.5">
                <RodzajIGmina oferta={oferta} />
              </td>
              <td className="px-4 py-2.5 tabular-nums">
                {format.m2(oferta.powierzchnia_m2)}
              </td>
              <td className="px-4 py-2.5 tabular-nums">
                {format.zl(oferta.cena_zl)}
              </td>
              <td className="px-4 py-2.5 tabular-nums">
                {oferta.cena_m2 === null ? "—" : Math.round(oferta.cena_m2)}
              </td>
              <td className="px-4 py-2.5 tabular-nums">
                <PozycjaWobecRynku rynek={oferta.rynek} />
              </td>
              <td className="px-4 py-2.5 tabular-nums">
                {oferta.media_koszt_pln === null ? (
                  <span className="text-slate-400">—</span>
                ) : (
                  `${Math.round(oferta.media_koszt_pln / 1000)} tys.`
                )}
              </td>
              <td className="px-4 py-2.5">
                <div className="flex flex-wrap gap-1">
                  {oferta.strefy_powodziowe.map((strefa) => (
                    <span
                      key={strefa}
                      title="strefa zagrożenia powodziowego"
                      className="pigulka bg-rose-100/80 text-xs text-rose-800 dark:bg-rose-400/15 dark:text-rose-200"
                    >
                      {strefa}
                    </span>
                  ))}
                  {oferta.klaster !== null && (
                    <span
                      title="ta sama działka jest wystawiona jeszcze raz, szczegóły na karcie"
                      className="pigulka bg-slate-200/70 text-xs text-slate-700 dark:bg-white/10 dark:text-slate-200"
                    >
                      duplikat
                    </span>
                  )}
                  {oferta.czerwone_flagi.length > 0 && (
                    <span
                      title={oferta.czerwone_flagi.join("\n")}
                      className="pigulka bg-amber-100/80 text-xs text-amber-800 dark:bg-amber-300/15 dark:text-amber-200"
                    >
                      {oferta.czerwone_flagi.length} ⚠
                    </span>
                  )}
                </div>
              </td>
              <td className="px-4 py-2.5 text-xs text-slate-500">
                {format.data(oferta.pierwszy_raz)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function Score({
  wartosc,
  kompletnosc,
}: {
  wartosc: number | null;
  kompletnosc: number | null;
}) {
  if (wartosc === null) {
    return (
      <span
        title="za mało danych, żeby policzyć wynik"
        className="text-slate-400"
      >
        — <span className="text-xs">brak danych</span>
      </span>
    );
  }
  const kolor =
    wartosc >= 70
      ? "text-emerald-600"
      : wartosc >= 50
        ? "text-slate-900 dark:text-slate-100"
        : "text-slate-500";
  return (
    <span className="tabular-nums">
      <span className={`font-semibold ${kolor}`}>{wartosc.toFixed(0)}</span>
      <span className="ml-1 text-xs text-slate-400" title="kompletność danych">
        {format.procent(kompletnosc)}
      </span>
    </span>
  );
}

/**
 * Rodzaj dzialki nad nazwa gminy.
 *
 * Rodzaj bez zrodla bylby twierdzeniem nie do sprawdzenia, dlatego w podpowiedzi
 * stoi, czy wzielismy go ze strefy planu ogolnego, czy z tresci ogloszenia.
 * Myslnik znaczy "ogloszenie nie mowi", a nie "zadna z czterech kategorii".
 */
function RodzajIGmina({ oferta }: { oferta: Oferta }) {
  const styl: Record<string, string> = {
    mieszkaniowa: "bg-sky-100/80 text-sky-800 dark:bg-sky-300/15 dark:text-sky-200",
    uslugowa: "bg-violet-100/80 text-violet-800 dark:bg-violet-300/15 dark:text-violet-200",
    przemyslowa: "bg-amber-100/80 text-amber-800 dark:bg-amber-300/15 dark:text-amber-200",
    lesna: "bg-emerald-100/80 text-emerald-800 dark:bg-emerald-300/15 dark:text-emerald-200",
  };
  return (
    <div className="leading-tight">
      {!oferta.rodzaj ? (
        <span className="text-slate-400" title="ogłoszenie nie mówi, jaka to działka">
          —
        </span>
      ) : (
        <span
          className={`pigulka text-xs ${styl[oferta.rodzaj] ?? ""}`}
          title={
            OPIS_ZRODLA_RODZAJU[oferta.rodzaj_zrodlo ?? ""] ?? "źródło nieznane"
          }
        >
          {nazwaRodzaju(oferta.rodzaj)}
        </span>
      )}
      <div
        className="mt-0.5 text-xs text-slate-500"
        title={oferta.region?.powiat ?? undefined}
      >
        {nazwaRegionu(oferta.region)}
      </div>
    </div>
  );
}

function StatusPlanu({
  status,
  wOuz,
}: {
  status: string | null;
  wOuz: boolean | null;
}) {
  if (!status) return <span className="text-slate-400">—</span>;
  const styl: Record<string, string> = {
    A: "bg-emerald-100/80 text-emerald-800 dark:bg-emerald-300/15 dark:text-emerald-200",
    B: "bg-emerald-50/90 text-emerald-700 dark:bg-emerald-300/10 dark:text-emerald-300",
    C: "bg-sky-100/80 text-sky-800 dark:bg-sky-300/15 dark:text-sky-200",
    D: "bg-rose-100/80 text-rose-800 dark:bg-rose-400/15 dark:text-rose-200",
    E: "bg-slate-200/70 text-slate-700 dark:bg-white/10 dark:text-slate-300",
    "?": "bg-slate-200/50 text-slate-500 dark:bg-white/5 dark:text-slate-400",
  };
  return (
    <span
      className={`pigulka font-mono text-xs ${styl[status] ?? styl["?"]}`}
    >
      {status}
      {wOuz ? " · OUZ" : ""}
    </span>
  );
}

function PozycjaWobecRynku({ rynek }: { rynek: PozycjaRynkowa | null }) {
  if (rynek === null) {
    return (
      <span
        className="text-slate-400"
        title="brak mediany dla tego obszaru i rodzaju gruntu"
      >
        —
      </span>
    );
  }

  // Prog 10% jest umowny i sluzy tylko do koloru: ponizej niego roznica miesci
  // sie w szumie samej mediany, wiec nie warto jej podswietlac.
  const kolor =
    rynek.odchylenie <= -0.1
      ? "text-emerald-700 dark:text-emerald-400"
      : rynek.odchylenie >= 0.1
        ? "text-red-700 dark:text-red-400"
        : "text-slate-500";

  const opis =
    `${Math.round(rynek.cena_zl_m2_norm)} zł/m² znormalizowane wobec mediany ` +
    `${Math.round(rynek.mediana_zl_m2)} zł/m²
` +
    `${rynek.obszar ?? "obszar"} (${rynek.poziom}), ${rynek.n} transakcji
` +
    `rodzaj: ${nazwaSegmentu(rynek.segment)}`;

  return (
    <span className={kolor} title={opis}>
      {format.procentZeZnakiem(rynek.odchylenie)}
      {rynek.n < 30 && (
        <span
          className="ml-1 text-xs text-slate-400"
          title="mediana z małej próby"
        >
          ?
        </span>
      )}
    </span>
  );
}
