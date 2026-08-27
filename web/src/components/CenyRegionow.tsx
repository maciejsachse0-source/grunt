"use client";

/**
 * Ceny transakcyjne w regionach: mediany per obszar i segment rynku.
 *
 * Zrodlem jest RCN, czyli ceny, po ktorych faktycznie podpisano akty notarialne,
 * a nie ceny ofertowe. Roznica miedzy jednym a drugim to zmierzony spread
 * (sekcja 5.6) i wlasnie dlatego ta tabela jest punktem odniesienia dla ofert.
 *
 * Trzy rzeczy sa tu widoczne celowo:
 * - mediana ZNORMALIZOWANA obok surowej, bo cena za m2 spada z powierzchnia
 *   dzialki i tylko znormalizowana nadaje sie do porownan (sekcja 5.2.1);
 * - liczba transakcji przy kazdym wierszu, bo mediana z 12 transakcji to co
 *   innego niz mediana z 600 (sekcja 7.1);
 * - rozstep miedzykwartylowy, bo mediana bez rozrzutu nie mowi, czy rynek jest
 *   jednorodny, czy sklada sie z dwoch roznych swiatow.
 */

import { Fragment, useEffect, useState } from "react";
import type { CenaRegionu, PoziomObszaru, SegmentRynku } from "@/lib/api";
import {
  format,
  nazwaSegmentu,
  pobierzCenyRegionow,
  pobierzSegmentyRynku,
} from "@/lib/api";
import { WykresCen } from "./WykresCen";
import { WyborGminy } from "./WyborGminy";

const SORTOWANIA: { wartosc: string; etykieta: string }[] = [
  { wartosc: "mediana", etykieta: "najdroższe" },
  { wartosc: "mediana_rosnaco", etykieta: "najtańsze" },
  { wartosc: "transakcje", etykieta: "najwięcej transakcji" },
  { wartosc: "dynamika", etykieta: "najszybciej rosnące" },
  { wartosc: "nazwa", etykieta: "alfabetycznie" },
];

export function CenyRegionow() {
  const [poziom, setPoziom] = useState<PoziomObszaru>("gmina");
  const [segment, setSegment] = useState("*");
  const [minN, setMinN] = useState(10);
  const [sort, setSort] = useState("mediana");
  const [segmenty, setSegmenty] = useState<SegmentRynku[]>([]);
  const [wiersze, setWiersze] = useState<CenaRegionu[] | null>(null);
  const [rozwiniety, setRozwiniety] = useState<string | null>(null);
  const [blad, setBlad] = useState<string | null>(null);

  useEffect(() => {
    let aktualne = true;
    pobierzSegmentyRynku(poziom)
      .then((dane) => aktualne && setSegmenty(dane.items))
      .catch(() => aktualne && setSegmenty([]));
    return () => {
      aktualne = false;
    };
  }, [poziom]);

  useEffect(() => {
    let aktualne = true;
    // Stan zmieniamy wylacznie w callbackach obietnicy: React 19 nie pozwala
    // wolac setState synchronicznie w ciele efektu, bo to kaskaduje renderowanie.
    pobierzCenyRegionow({ poziom, segment, min_n: minN, sort })
      .then((dane) => {
        if (aktualne) {
          setWiersze(dane.items);
          setBlad(null);
        }
      })
      .catch((e) => {
        if (aktualne) {
          setWiersze([]);
          setBlad(String(e));
        }
      });
    return () => {
      aktualne = false;
    };
  }, [poziom, segment, minN, sort]);

  return (
    <div className="flex flex-col gap-4">
      <div className="szklo flex flex-wrap items-end gap-4 px-5 py-4 text-sm">
        <Pole etykieta="obszar">
          <select
            value={poziom}
            onChange={(e) => {
              setPoziom(e.target.value as PoziomObszaru);
              // Zwijamy wykres razem ze zmiana filtru: otwarty pokazywalby
              // inny obszar albo segment niz tabela nad nim.
              setRozwiniety(null);
            }}
            className="pole w-auto text-sm"
          >
            <option value="gmina">gminy</option>
            <option value="powiat">powiaty</option>
            <option value="wojewodztwo">województwa</option>
          </select>
        </Pole>

        <Pole etykieta="rodzaj gruntu">
          <select
            value={segment}
            onChange={(e) => {
              setSegment(e.target.value);
              setRozwiniety(null);
            }}
            className="pole w-auto text-sm"
          >
            {segmenty.map((s) => (
              <option key={s.segment} value={s.segment}>
                {nazwaSegmentu(s.segment)} (
                {s.transakcje.toLocaleString("pl-PL")})
              </option>
            ))}
          </select>
        </Pole>

        <Pole etykieta="min. transakcji">
          <input
            type="number"
            value={minN}
            min={1}
            onChange={(e) => setMinN(Math.max(1, Number(e.target.value) || 1))}
            className="pole w-20 text-sm"
          />
        </Pole>

        <Pole etykieta="sortowanie">
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="pole w-auto text-sm"
          >
            {SORTOWANIA.map((s) => (
              <option key={s.wartosc} value={s.wartosc}>
                {s.etykieta}
              </option>
            ))}
          </select>
        </Pole>
      </div>

      {blad && (
        <p className="rounded-lg border border-rose-600/25 bg-rose-200/40 p-3 text-xs text-rose-700">
          {blad}
        </p>
      )}

      <div className="szklo overflow-hidden">
        <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="tabela-naglowek text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">obszar</th>
              <th
                className="px-4 py-2.5 text-right"
                title="cena za m² sprowadzona do działki 1000 m²"
              >
                mediana zł/m²
              </th>
              <th
                className="px-4 py-2.5 text-right"
                title="połowa transakcji mieści się w tym zakresie"
              >
                kwartyle
              </th>
              <th
                className="px-4 py-2.5 text-right"
                title="mediana cen faktycznie zapłaconych, bez normalizacji"
              >
                surowa
              </th>
              <th
                className="px-4 py-2.5 text-right"
                title="liczba transakcji, na których stoi mediana"
              >
                transakcji
              </th>
              <th className="px-4 py-3 text-right">rocznie</th>
              <th className="px-4 py-3 text-right">ofert w bazie</th>
            </tr>
          </thead>
          <tbody>
            {wiersze === null && (
              <tr>
                <td
                  colSpan={7}
                  className="px-3 py-6 text-center text-slate-400"
                >
                  wczytywanie…
                </td>
              </tr>
            )}
            {wiersze?.length === 0 && (
              <tr>
                <td
                  colSpan={7}
                  className="px-3 py-6 text-center text-sm text-slate-500"
                >
                  Żaden obszar nie ma tylu transakcji w tym segmencie. Zmniejsz
                  próg albo wybierz „wszystkie razem”.
                </td>
              </tr>
            )}
            {wiersze?.map((r) => (
              <Fragment key={r.teryt}>
                <tr
                  onClick={() =>
                    setRozwiniety(rozwiniety === r.teryt ? null : r.teryt)
                  }
                  className={`wiersz cursor-pointer ${
                    rozwiniety === r.teryt ? "wiersz-wybrany" : ""
                  }`}
                  title="kliknij, żeby zobaczyć wykres cen w czasie"
                >
                  <td className="px-4 py-2.5">
                    <span className="mr-1 text-slate-400">
                      {rozwiniety === r.teryt ? "▾" : "▸"}
                    </span>
                    <span className="font-medium">{r.nazwa ?? r.teryt}</span>
                    {r.powiat && r.nazwa && (
                      <span className="ml-2 text-xs text-slate-500">
                        {r.powiat}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right font-semibold tabular-nums">
                    {Math.round(r.mediana).toLocaleString("pl-PL")}
                  </td>
                  <td className="px-4 py-2.5 text-right text-xs tabular-nums text-slate-500">
                    {Math.round(r.p25).toLocaleString("pl-PL")}–
                    {Math.round(r.p75).toLocaleString("pl-PL")}
                  </td>
                  <td className="px-4 py-2.5 text-right text-xs tabular-nums text-slate-500">
                    {Math.round(r.mediana_surowa).toLocaleString("pl-PL")}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {r.n.toLocaleString("pl-PL")}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {r.dynamika === null ? (
                      <span className="text-slate-400">—</span>
                    ) : (
                      <span
                        className={
                          r.dynamika > 0
                            ? "text-emerald-700 dark:text-emerald-400"
                            : "text-red-700 dark:text-red-400"
                        }
                      >
                        {format.procentZeZnakiem(r.dynamika, 1)}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-500">
                    {r.oferty || "—"}
                  </td>
                </tr>
                {rozwiniety === r.teryt && (
                  <tr className="wiersz">
                    <td colSpan={7} className="bg-slate-50 p-0">
                      {/* Wykres zawsze na terenie gminy. Przy powiecie
                          i wojewodztwie wybieramy gmine wewnatrz obszaru,
                          bo mediana z calego powiatu miesza rozne rynki. */}
                      {poziom === "gmina" ? (
                        <WykresCen
                          poziom="gmina"
                          teryt={r.teryt}
                          nazwa={r.nazwa}
                          segment={segment}
                        />
                      ) : (
                        <WyborGminy
                          rodzic={r.teryt}
                          poziomRodzica={poziom}
                          nazwaObszaru={r.nazwa}
                          segment={segment}
                        />
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        </div>
      </div>

      <p className="szklo px-5 py-4 text-xs leading-relaxed text-slate-500">
        Źródło: Rejestr Cen Nieruchomości, transakcje z ostatnich 24 miesięcy,
        zindeksowane na dziś dynamiką danego obszaru. Mediana jest liczona z cen
        sprowadzonych do działki 1000 m², bo cena za m² systematycznie spada
        wraz z powierzchnią — porównywanie surowych cen działki 400 m² i 4 ha
        nie ma sensu. To ceny <strong>transakcyjne</strong>, nie ofertowe:
        oferty leżą powyżej o zmierzony spread.
      </p>
    </div>
  );
}

function Pole({
  etykieta,
  children,
}: {
  etykieta: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs uppercase tracking-wide text-slate-500">
        {etykieta}
      </span>
      {children}
    </label>
  );
}
