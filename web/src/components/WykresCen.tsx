"use client";

/**
 * Wykres cen gruntow w czasie dla jednego obszaru.
 *
 * FORMA. Jedna seria (mediana kwartalna) plus pasmo miedzykwartylowe jako tlo.
 * Trend w czasie to linia, a przy jednej serii legenda jest zbedna: tytul mowi,
 * co jest narysowane. Liczba transakcji NIE dostaje drugiej osi (dwie skale na
 * jednym wykresie to najczestszy blad wykresow), tylko wlasny pasek pod spodem.
 *
 * CO POKAZUJEMY, A CZEGO NIE:
 * - ceny sa znormalizowane do dzialki 1000 m2, bo cena za m2 spada z powierzchnia;
 * - NIE indeksujemy ich na dzis, inaczej wykres splaszczylby to, co ma pokazac;
 * - kwartal z mniej niz pieciu transakcjami nie ma punktu i nie jest
 *   interpolowany: dziura znaczy "nic sie nie sprzedalo", a nie "cena zero";
 * - kwartal niepelny (RCN publikuje z opoznieniem) jest pusty w srodku
 *   i opisany, bo inaczej wyglada jak skok cen;
 * - trend roczny pojawia sie tylko wtedy, gdy jest mierzalny: potrzeba szesciu
 *   pelnych kwartalow, dwoch lat okna i mediany dziesieciu transakcji na
 *   kwartal. Inaczej pokazujemy, ze go nie ma, zamiast pokazac liczbe.
 */

import { useEffect, useMemo, useState } from "react";
import type { HistoriaCen, PoziomObszaru } from "@/lib/api";
import { format, nazwaSegmentu, pobierzHistorieCen } from "@/lib/api";

interface Props {
  poziom: PoziomObszaru;
  teryt: string;
  nazwa: string | null;
  segment: string;
}

const SZEROKOSC = 720;
const WYSOKOSC = 260;
const WYSOKOSC_PASKA = 44;
const MARGINES = { gora: 16, prawo: 56, dol: 28, lewo: 52 };

export function WykresCen({ poziom, teryt, nazwa, segment }: Props) {
  const [dane, setDane] = useState<HistoriaCen | null>(null);
  const [blad, setBlad] = useState<string | null>(null);
  const [aktywny, setAktywny] = useState<number | null>(null);

  useEffect(() => {
    let aktualne = true;
    pobierzHistorieCen({ poziom, teryt, segment })
      .then((d) => {
        if (aktualne) {
          setDane(d);
          setBlad(null);
        }
      })
      .catch((e) => {
        if (aktualne) {
          setDane(null);
          setBlad(String(e));
        }
      });
    return () => {
      aktualne = false;
    };
  }, [poziom, teryt, segment]);

  const wykres = useMemo(() => {
    if (!dane || dane.punkty.length < 2) return null;

    const punkty = dane.punkty;
    const maxCena = Math.max(...punkty.map((p) => p.p75));
    const minCena = Math.min(...punkty.map((p) => p.p25));
    // Skala zaczyna sie od zera tylko wtedy, gdy dane sa blisko zera. Przy
    // cenach 150-250 zl/m2 os od zera zamienilaby caly ruch w plaska kreske.
    const dol = minCena < maxCena * 0.35 ? 0 : minCena * 0.9;
    const gora = maxCena * 1.05;

    const szerokoscPola = SZEROKOSC - MARGINES.lewo - MARGINES.prawo;
    const wysokoscPola = WYSOKOSC - MARGINES.gora - MARGINES.dol;
    const x = (i: number) =>
      MARGINES.lewo +
      (punkty.length === 1
        ? szerokoscPola / 2
        : (i * szerokoscPola) / (punkty.length - 1));
    const y = (v: number) =>
      MARGINES.gora +
      wysokoscPola -
      ((v - dol) / (gora - dol || 1)) * wysokoscPola;

    const linia = punkty
      .map((p, i) => `${i === 0 ? "M" : "L"} ${x(i)} ${y(p.mediana)}`)
      .join(" ");
    const pasmo =
      punkty
        .map((p, i) => `${i === 0 ? "M" : "L"} ${x(i)} ${y(p.p75)}`)
        .join(" ") +
      " " +
      punkty
        .slice()
        .reverse()
        .map((p, i) => `L ${x(punkty.length - 1 - i)} ${y(p.p25)}`)
        .join(" ") +
      " Z";

    const maxN = Math.max(...punkty.map((p) => p.n));
    const siatka = [0, 0.25, 0.5, 0.75, 1].map((u) => dol + (gora - dol) * u);

    return { punkty, x, y, linia, pasmo, siatka, maxN, wysokoscPola };
  }, [dane]);

  if (blad) {
    return (
      <p className="p-3 text-xs text-red-600">
        Nie udało się pobrać historii cen: {blad}
      </p>
    );
  }
  if (!dane) {
    return <p className="p-3 text-xs text-slate-400">wczytywanie wykresu…</p>;
  }
  if (!wykres) {
    return (
      <p className="p-3 text-xs text-slate-500">
        Za mało transakcji, żeby narysować szereg czasowy dla tego obszaru i
        rodzaju gruntu. Kwartał musi mieć co najmniej 5 transakcji. Spróbuj
        poziomu powiatu albo rodzaju „wszystkie razem”.
      </p>
    );
  }

  const { punkty, x, y, linia, pasmo, siatka, maxN } = wykres;
  const wybrany = aktywny === null ? null : punkty[aktywny];
  const ostatni = punkty[punkty.length - 1];

  return (
    <div className="wykres-cen p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">
          {nazwa ?? teryt}: mediana ceny gruntu, {nazwaSegmentu(segment)}
        </h3>
        <span className="text-xs text-slate-500">
          {dane.zmiana_roczna === null ? (
            <span title="Trend wymaga sześciu pełnych kwartałów, dwóch lat okna i mediany dziesięciu transakcji na kwartał. Ten szereg jest za cienki — liczba byłaby zgadywaniem.">
              trend niemierzalny
            </span>
          ) : (
            <>
              trend{" "}
              <strong
                title="Mediana nachyleń wszystkich par kwartałów (Theil-Sen) po logarytmie ceny, liczona tylko z pełnych kwartałów. Nie jest to różnica pierwszego i ostatniego punktu."
                className={
                  dane.zmiana_roczna > 0
                    ? "text-emerald-700 dark:text-emerald-400"
                    : "text-red-700 dark:text-red-400"
                }
              >
                {format.procentZeZnakiem(dane.zmiana_roczna, 1)} rocznie
              </strong>
            </>
          )}{" "}
          · {dane.transakcje.toLocaleString("pl-PL")} transakcji
        </span>
      </div>

      <svg
        viewBox={`0 0 ${SZEROKOSC} ${WYSOKOSC}`}
        className="mt-2 w-full"
        role="img"
        aria-label={`Mediana ceny za metr kwadratowy w obszarze ${nazwa ?? teryt}, kwartalnie`}
      >
        {siatka.map((wartosc) => (
          <g key={wartosc}>
            <line
              x1={MARGINES.lewo}
              x2={SZEROKOSC - MARGINES.prawo}
              y1={y(wartosc)}
              y2={y(wartosc)}
              className="stroke-slate-300/50 dark:stroke-slate-600/40"
              strokeWidth={1}
            />
            <text
              x={MARGINES.lewo - 8}
              y={y(wartosc) + 4}
              textAnchor="end"
              className="fill-slate-500 text-[10px]"
            >
              {Math.round(wartosc)}
            </text>
          </g>
        ))}

        {/* Pasmo miedzykwartylowe: polowa transakcji miesci sie w tym zakresie */}
        <path d={pasmo} className="fill-[var(--seria)]" opacity={0.1} />
        <path
          d={linia}
          fill="none"
          className="stroke-[var(--seria)]"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {punkty.map((p, i) => (
          <g key={p.okres}>
            <circle
              cx={x(i)}
              cy={y(p.mediana)}
              r={aktywny === i ? 6 : 4}
              className={p.pelny ? "fill-[var(--seria)]" : "fill-[var(--tlo)]"}
              stroke={p.pelny ? "var(--tlo)" : "var(--seria)"}
              strokeWidth={2}
            />
            {/* Cel trafienia szerszy niz punkt: 4 px trudno trafic myszka */}
            <rect
              x={x(i) - 14}
              y={MARGINES.gora}
              width={28}
              height={WYSOKOSC - MARGINES.gora - MARGINES.dol}
              fill="transparent"
              onMouseEnter={() => setAktywny(i)}
              onMouseLeave={() => setAktywny(null)}
            />
          </g>
        ))}

        {/* Etykieta tylko przy ostatnim punkcie: liczba przy kazdym to chaos */}
        <text
          x={x(punkty.length - 1) + 10}
          y={y(ostatni.mediana) + 4}
          className="fill-slate-600 text-[11px] font-medium dark:fill-slate-300"
        >
          {Math.round(ostatni.mediana)}
        </text>

        {punkty.map((p, i) =>
          i % 2 === 0 || i === punkty.length - 1 ? (
            <text
              key={`o-${p.okres}`}
              x={x(i)}
              y={WYSOKOSC - 8}
              textAnchor="middle"
              className="fill-slate-500 text-[10px]"
            >
              {p.etykieta.replace(" ", " ")}
            </text>
          ) : null,
        )}
      </svg>

      {/* Liczba transakcji jako osobny pasek, nie druga os na tym samym wykresie.
          Podpisy sa w HTML nad paskiem, bo w SVG nachodzily na pierwszy slupek. */}
      <div className="flex items-baseline justify-between px-1 text-[10px] text-slate-500">
        <span>transakcji w kwartale</span>
        <span>najwięcej: {maxN}</span>
      </div>
      <svg
        viewBox={`0 0 ${SZEROKOSC} ${WYSOKOSC_PASKA}`}
        className="w-full"
        role="img"
        aria-label="Liczba transakcji w kwartale"
      >
        {punkty.map((p, i) => {
          const wysokosc = Math.max(2, (p.n / maxN) * (WYSOKOSC_PASKA - 16));
          return (
            <rect
              key={`n-${p.okres}`}
              x={x(i) - 6}
              y={WYSOKOSC_PASKA - 12 - wysokosc}
              width={12}
              height={wysokosc}
              rx={3}
              className="fill-[var(--seria)]"
              opacity={aktywny === i ? 0.75 : 0.35}
            />
          );
        })}
      </svg>

      <div className="min-h-[2.5rem] text-xs">
        {wybrany ? (
          <p>
            <strong>{wybrany.etykieta}</strong>: mediana{" "}
            <strong>{Math.round(wybrany.mediana)} zł/m²</strong>, połowa
            transakcji w zakresie {Math.round(wybrany.p25)}–
            {Math.round(wybrany.p75)} zł/m², {wybrany.n} transakcji
            {!wybrany.pelny &&
              " — kwartał niepełny, dane RCN kończą się " + dane.koniec_danych}
          </p>
        ) : (
          <p className="text-slate-500">
            Ceny sprowadzone do działki 1000 m², bez indeksacji na dziś. Pasmo
            to zakres międzykwartylowy. Pusty punkt oznacza kwartał niepełny.
            {dane.kwartaly_pominiete > 0 &&
              ` Pominięto ${dane.kwartaly_pominiete} kwartałów z mniej niż 5 transakcjami.`}
          </p>
        )}
      </div>
    </div>
  );
}
