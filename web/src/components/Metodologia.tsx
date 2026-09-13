"use client";

/**
 * Zakladka weryfikacyjna: jak liczony jest score, wycena, deal score i mediany.
 *
 * Strona jest po to, zeby dalo sie SPRAWDZIC, a nie zeby przekonac. Dlatego
 * kazda liczba przychodzi z /api/metodologia, a ta z kolei importuje progi
 * i wagi wprost z modulow scoring/ i liczy pokrycie zapytaniami do bazy.
 * Nic tutaj nie jest przepisane recznie, wiec strona nie moze rozjechac sie
 * z kodem: gdy ktos zmieni wage filaru, zmieni sie tez ten ekran.
 *
 * Uklad idzie za droga danych, a nie za struktura kodu:
 *   zrodla -> wzbogacenie -> filary -> score -> wycena -> deal score.
 */

import { useEffect, useState } from "react";
import type { Metodologia as Dane } from "@/lib/api";
import { PROG_OKAZJI, format, pobierzMetodologie } from "@/lib/api";

export function Metodologia() {
  const [dane, setDane] = useState<Dane | null>(null);
  const [blad, setBlad] = useState<string | null>(null);

  useEffect(() => {
    let aktualne = true;
    pobierzMetodologie()
      .then((d) => {
        if (aktualne) {
          setDane(d);
          setBlad(null);
        }
      })
      .catch((e) => {
        if (aktualne) setBlad(String(e));
      });
    return () => {
      aktualne = false;
    };
  }, []);

  if (blad) {
    return (
      <p className="rounded-lg border border-rose-600/25 bg-rose-200/40 p-4 text-sm text-rose-700">
        Nie udało się pobrać opisu metody: {blad}
      </p>
    );
  }
  if (!dane) return <p className="p-4 text-sm text-slate-400">wczytywanie…</p>;

  const { score, wycena, deal, rynek, prywatnosc } = dane;

  return (
    <div className="flex max-w-4xl flex-col gap-5 text-sm leading-relaxed">
      <section className="szklo px-6 py-5">
        <h2 className="text-lg font-semibold tracking-tight">
          Jak to jest liczone
        </h2>
        <p className="mt-2 text-slate-600 dark:text-slate-300">
          Wszystkie progi, wagi i parametry na tej stronie są odczytywane wprost
          z modułów <code>scoring/</code>, a pokrycie i rozkłady z bieżących
          zapytań do bazy. Nic nie jest tu przepisane ręcznie, więc jeśli ta
          strona pokazuje wagę 35%, to znaczy, że taka waga naprawdę weszła do
          ostatniego liczenia.
        </p>
        <p className="mt-2 text-slate-600 dark:text-slate-300">
          Zero w kolumnie „ma dane” nie jest błędem strony. To informacja, po
          którą się tu przychodzi: filar istnieje w kodzie, ale nie dostaje
          danych, więc jego waga jest rozdzielana między pozostałe.
        </p>
      </section>

      {/* ------------------------------------------------------------ SCORE */}
      <Sekcja
        tytul="1. Score potencjału"
        podtytul="ocena działki w skali 0-100, niezależna od ceny"
      >
        <Wzor>{score.wzor}</Wzor>
        <p>{score.wyjasnienie_wzoru}</p>

        <Tabela
          naglowki={[
            "filar",
            "waga",
            "skąd dane",
            "ma dane",
            "co dokładnie liczy",
          ]}
          wyrownanie={["left", "right", "left", "right", "left"]}
        >
          {score.filary.map((f) => {
            const brak = f.ma_dane === 0;
            return (
              <tr
                key={f.klucz}
                className="wiersz-statyczny align-top"
              >
                <td className="px-2 py-2 font-medium">{f.nazwa}</td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {f.waga_detaliczny === null
                    ? "—"
                    : `${Math.round(f.waga_detaliczny * 100)}%`}
                </td>
                <td className="px-2 py-2 text-xs text-slate-500">
                  {f.zrodla.length ? f.zrodla.join(", ") : "—"}
                </td>
                <td
                  className={`px-2 py-2 text-right tabular-nums ${
                    brak ? "font-semibold text-red-700 dark:text-red-400" : ""
                  }`}
                >
                  {f.ma_dane} / {f.z_ilu}
                </td>
                <td className="px-2 py-2 text-xs text-slate-600 dark:text-slate-300">
                  {f.jak}
                </td>
              </tr>
            );
          })}
        </Tabela>
        <p className="text-xs text-slate-500">
          Waga z profilu detalicznego. Profil deweloperski przesuwa planistykę
          na{" "}
          {Math.round(
            (score.filary.find((f) => f.klucz === "planistyka")
              ?.waga_deweloper ?? 0) * 100,
          )}
          % i dokłada filar chłonności.
        </p>

        <Uwaga>{score.regula_coverage}</Uwaga>

        <h4 className="mt-2 font-medium">Mnożniki zerujące (gates)</h4>
        <p>{score.wyjasnienie_gates}</p>
        <Tabela
          naglowki={["gate", "mnożnik", "dlaczego", "zadziałał"]}
          wyrownanie={["left", "right", "left", "right"]}
        >
          {score.gates.map((g) => (
            <tr
              key={g.nazwa}
              className="wiersz-statyczny align-top"
            >
              <td className="px-2 py-2 font-mono text-xs">{g.nazwa}</td>
              <td className="px-2 py-2 text-right tabular-nums">
                × {g.mnoznik.toFixed(2)}
              </td>
              <td className="px-2 py-2 text-xs text-slate-600 dark:text-slate-300">
                {g.powod}
              </td>
              <td className="px-2 py-2 text-right tabular-nums">
                {g.aktywny_w_ofertach || (
                  <span className="text-slate-400">0</span>
                )}
              </td>
            </tr>
          ))}
        </Tabela>

        <h4 className="mt-2 font-medium">Status planistyczny</h4>
        <p>
          Najsilniejsza pojedyncza dźwignia wartości. Status wchodzi do filaru
          planistyki jako punkty, a niezależnie od tego zawęża mnożnik wartości
          działki.
        </p>
        <Tabela
          naglowki={[
            "status",
            "znaczenie",
            "mnożnik wartości",
            "punkty",
            "ofert",
          ]}
          wyrownanie={["left", "left", "right", "right", "right"]}
        >
          {score.statusy_planistyczne.map((s) => (
            <tr
              key={s.status}
              className="wiersz-statyczny"
            >
              <td className="px-2 py-2 font-mono font-semibold">{s.status}</td>
              <td className="px-2 py-2 text-xs">{s.opis}</td>
              <td className="px-2 py-2 text-right tabular-nums">
                {s.mnoznik_min.toFixed(2)}–{s.mnoznik_max.toFixed(2)}
              </td>
              <td className="px-2 py-2 text-right tabular-nums">{s.punkty}</td>
              <td className="px-2 py-2 text-right tabular-nums">{s.ofert}</td>
            </tr>
          ))}
        </Tabela>

        <h4 className="mt-2 font-medium">Co z tego wyszło</h4>
        <Liczby
          pozycje={[
            ["ocenionych ofert", score.rozklad.ocenionych],
            ["z wynikiem", score.rozklad.z_wynikiem],
            [
              "bez wyniku (za mało danych)",
              score.rozklad.bez_wyniku,
              score.rozklad.bez_wyniku > 0 ? "uwaga" : undefined,
            ],
            ["mediana score", score.rozklad.mediana],
            [
              "zakres",
              `${score.rozklad.min ?? "—"} – ${score.rozklad.max ?? "—"}`,
            ],
            [
              "mediana kompletności",
              score.rozklad.mediana_kompletnosci === null
                ? "—"
                : format.procent(score.rozklad.mediana_kompletnosci),
            ],
            [
              "ostatnie liczenie",
              score.rozklad.ostatnie_liczenie
                ? format.data(score.rozklad.ostatnie_liczenie)
                : "nigdy",
            ],
          ]}
        />
      </Sekcja>

      {/* ----------------------------------------------------------- WYCENA */}
      <Sekcja
        tytul="2. Wycena"
        podtytul="ile ta działka jest warta według cen transakcyjnych"
      >
        <p className="font-medium">{wycena.model}</p>
        <p>{wycena.opis}</p>
        <p>{wycena.normalizacja}</p>

        <h4 className="mt-2 font-medium">Parametry modelu</h4>
        <Tabela
          naglowki={["parametr", "wartość"]}
          wyrownanie={["left", "right"]}
        >
          {Object.entries(wycena.parametry).map(([k, v]) => (
            <tr
              key={k}
              className="wiersz-statyczny"
            >
              <td className="px-2 py-1.5 font-mono text-xs">{k}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">
                {v.toLocaleString("pl-PL")}
              </td>
            </tr>
          ))}
        </Tabela>
        <Uwaga>{wycena.wyjasnienie_sigma}</Uwaga>

        <h4 className="mt-2 font-medium">
          Wykładnik skali β₁, kalibrowany na własnych danych
        </h4>
        <p>{wycena.wyjasnienie_beta1}</p>
        <Tabela
          naglowki={["segment rynku", "β₁", "transakcji", "źródło"]}
          wyrownanie={["left", "right", "right", "left"]}
        >
          {wycena.beta1.map((b) => (
            <tr
              key={b.segment ?? "-"}
              className="wiersz-statyczny"
            >
              <td className="px-2 py-1.5">{b.segment}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">
                {b.wartosc?.toFixed(3)}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">
                {b.n?.toLocaleString("pl-PL")}
              </td>
              <td className="px-2 py-1.5 text-xs text-slate-500">{b.zrodlo}</td>
            </tr>
          ))}
        </Tabela>
      </Sekcja>

      {/* ------------------------------------------------------ DEAL SCORE */}
      <Sekcja
        tytul="3. Deal score"
        podtytul="czy ta cena jest niska wobec wyceny, i czy na pewno"
      >
        <Wzor>{deal.wzor}</Wzor>
        <p>{deal.opis}</p>

        <h4 className="mt-2 font-medium">Spread ofertowo-transakcyjny</h4>
        <p>{deal.wyjasnienie_spreadu}</p>
        {deal.spread ? (
          <Liczby
            pozycje={[
              [
                "zmierzony spread",
                deal.spread.wartosc === null
                  ? "—"
                  : format.procentZeZnakiem(deal.spread.wartosc, 1),
              ],
              ["na ilu ofertach", deal.spread.n],
              ["metoda", deal.spread.zrodlo],
              [
                "kiedy zmierzony",
                deal.spread.kiedy ? format.data(deal.spread.kiedy) : "—",
              ],
            ]}
          />
        ) : (
          <Uwaga>
            Spread nie jest zmierzony, więc deal score porównuje cenę ofertową
            wprost z wyceną transakcyjną i wychodzi systematycznie ujemny.
          </Uwaga>
        )}

        <h4 className="mt-2 font-medium">Próg okazji</h4>
        <p>{deal.wyjasnienie_progu}</p>
        {deal.prog_okazji !== PROG_OKAZJI && (
          <Uwaga>
            Próg w interfejsie ({PROG_OKAZJI}) rozjechał się z progiem w kodzie
            scoringu ({deal.prog_okazji}). Tabela ofert wyróżnia inne oferty niż
            ta strona opisuje.
          </Uwaga>
        )}

        <h4 className="mt-2 font-medium">Rozkład na obecnych danych</h4>
        <Liczby
          pozycje={[
            ["ofert z deal score", deal.rozklad.z_deal_score],
            ["mediana", deal.rozklad.mediana],
            [
              "kwartyle",
              `${deal.rozklad.p25?.toFixed(2) ?? "—"} … ${deal.rozklad.p75?.toFixed(2) ?? "—"}`,
            ],
            [
              "zakres",
              `${deal.rozklad.min?.toFixed(1) ?? "—"} … ${deal.rozklad.max?.toFixed(1) ?? "—"}`,
            ],
            [`powyżej progu ${deal.prog_okazji}`, deal.rozklad.powyzej_progu],
          ]}
        />
        <p className="text-xs text-slate-500">
          Mediana blisko zera znaczy, że kalibracja działa: połowa ofert leży
          powyżej, połowa poniżej wyceny podniesionej o spread. Mediana mocno
          ujemna oznaczałaby, że porównujemy ceny ofertowe z transakcyjnymi bez
          korekty.
        </p>
      </Sekcja>

      {/* ------------------------------------------------------ CENY REGION */}
      <Sekcja
        tytul="4. Mediany i ceny w regionach"
        podtytul="punkt odniesienia, z którym porównywana jest oferta"
      >
        <p>{rynek.opis}</p>
        <p>{rynek.wybor_poziomu}</p>
        <p>{rynek.filtr_transakcji}</p>
        <p>{rynek.trend}</p>

        <h4 className="mt-2 font-medium">Progi</h4>
        <Tabela naglowki={["próg", "wartość"]} wyrownanie={["left", "right"]}>
          {Object.entries(rynek.progi).map(([k, v]) => (
            <tr
              key={k}
              className="wiersz-statyczny"
            >
              <td className="px-2 py-1.5 font-mono text-xs">{k}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">
                {v.toLocaleString("pl-PL")}
              </td>
            </tr>
          ))}
        </Tabela>

        <Liczby
          pozycje={Object.entries(rynek.stan).map(([k, v]) => [
            k.replaceAll("_", " "),
            v,
          ])}
        />
      </Sekcja>

      {/* ----------------------------------------------------------- ZRODLA */}
      <Sekcja
        tytul="5. Skąd biorą się dane"
        podtytul="usługi publiczne, po jednym zapytaniu na warstwę"
      >
        <Tabela
          naglowki={["źródło", "co daje", "udanych", "błędów"]}
          wyrownanie={["left", "left", "right", "right"]}
        >
          {dane.zrodla.map((z) => (
            <tr
              key={z.klucz}
              className="wiersz-statyczny align-top"
            >
              <td className="px-2 py-2">
                <div className="font-medium">{z.nazwa}</div>
                <div className="break-all font-mono text-[10px] text-slate-400">
                  {z.url}
                </div>
              </td>
              <td className="px-2 py-2 text-xs text-slate-600 dark:text-slate-300">
                {z.co_daje}
                <div className="mt-1 text-slate-500">{z.uwaga}</div>
              </td>
              <td className="px-2 py-2 text-right tabular-nums">
                {z.udanych_odpytan !== null ? (
                  z.udanych_odpytan
                ) : z.wierszy_w_bazie !== null ? (
                  <span title="zrodlo odpytywane wsadowo: pokazujemy wiersze w bazie">
                    {z.wierszy_w_bazie.toLocaleString("pl-PL")} wierszy
                  </span>
                ) : (
                  <span className="text-slate-400">—</span>
                )}
              </td>
              <td
                className={`px-2 py-2 text-right tabular-nums ${
                  z.bledow > 0 ? "text-amber-700 dark:text-amber-400" : ""
                }`}
              >
                {z.bledow}
              </td>
            </tr>
          ))}
        </Tabela>
        <p className="text-xs text-slate-500">
          „Udanych” liczy oferty, dla których krok wzbogacania zakończył się
          odpowiedzią usługi. Różnica wobec liczby wzbogaconych ofert to
          działki, dla których usługa nie odpowiedziała albo nie było czego
          pytać — te filary zostają puste i obniżają kompletność.
        </p>
      </Sekcja>

      {/* ---------------------------------------------------------- ZADANIA */}
      <Sekcja
        tytul="6. Co i jak często się odświeża"
        podtytul="kolejka zadań, harmonogram z jobs/scheduler.py"
      >
        <Tabela
          naglowki={["zadanie", "co robi", "co ile", "ostatnio"]}
          wyrownanie={["left", "left", "right", "left"]}
        >
          {dane.zadania.map((z) => (
            <tr
              key={z.kind}
              className="wiersz-statyczny"
            >
              <td className="px-2 py-1.5 font-mono text-xs">{z.kind}</td>
              <td className="px-2 py-1.5 text-xs">{z.opis}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">
                {z.co_ile_godzin >= 24
                  ? `${z.co_ile_godzin / 24} dni`
                  : `${z.co_ile_godzin} h`}
              </td>
              <td className="px-2 py-1.5 text-xs">
                {z.ostatnie ? (
                  format.data(z.ostatnie)
                ) : (
                  <span className="text-amber-700 dark:text-amber-400">
                    nigdy
                  </span>
                )}
                {z.status && z.status !== "done" && (
                  <span className="ml-1 text-red-700 dark:text-red-400">
                    ({z.status})
                  </span>
                )}
              </td>
            </tr>
          ))}
        </Tabela>
      </Sekcja>

      {/* ------------------------------------------------------- PRYWATNOSC */}
      <Sekcja
        tytul="7. Czego system nie zapisuje"
        podtytul="audyt schematu bazy, nie deklaracja"
      >
        <p>{prywatnosc.zasada}</p>
        <p className="text-xs text-slate-500">{prywatnosc.co_sprawdzamy}</p>

        {prywatnosc.naruszenia.length === 0 ? (
          <p className="rounded-xl border border-emerald-400/35 bg-emerald-400/10 p-3 text-xs text-emerald-200">
            Audyt czysty: poza wymienionymi niżej wyjątkami w schemacie nie ma
            kolumny, która mogłaby przechowywać dane osobowe ogłoszeniodawcy.
          </p>
        ) : (
          <div className="rounded-lg border border-rose-600/25 bg-rose-200/40 p-3 text-xs text-rose-700">
            <strong>Naruszenie zasady.</strong> Te kolumny nie mają
            uzasadnienia:
            <ul className="mt-1 list-inside list-disc">
              {prywatnosc.naruszenia.map((n) => (
                <li key={`${n.table_name}.${n.column_name}`}>
                  <code>
                    {n.table_name}.{n.column_name}
                  </code>
                </li>
              ))}
            </ul>
          </div>
        )}

        <Tabela
          naglowki={["kolumna", "dlaczego jest dozwolona"]}
          wyrownanie={["left", "left"]}
        >
          {prywatnosc.dozwolone.map((d) => (
            <tr
              key={`${d.table_name}.${d.column_name}`}
              className="wiersz-statyczny"
            >
              <td className="px-2 py-1.5 font-mono text-xs">
                {d.table_name}.{d.column_name}
              </td>
              <td className="px-2 py-1.5 text-xs">{d.uzasadnienie}</td>
            </tr>
          ))}
        </Tabela>
      </Sekcja>

      {/* ------------------------------------------------------------- BAZA */}
      <Sekcja tytul="8. Stan bazy" podtytul="ile czego jest w tej chwili">
        <Liczby
          pozycje={Object.entries(dane.dane).map(([k, v]) => [
            k.replaceAll("_", " "),
            v,
          ])}
        />
      </Sekcja>
    </div>
  );
}

// ------------------------------------------------------------- elementy

function Sekcja({
  tytul,
  podtytul,
  children,
}: {
  tytul: string;
  podtytul: string;
  children: React.ReactNode;
}) {
  return (
    <section className="szklo flex flex-col gap-3 px-6 py-5">
      <div>
        <h3 className="text-base font-semibold tracking-tight">{tytul}</h3>
        <p className="text-xs text-slate-500">{podtytul}</p>
      </div>
      {children}
    </section>
  );
}

function Wzor({ children }: { children: React.ReactNode }) {
  return (
    <pre className="overflow-x-auto rounded-lg border border-slate-200 bg-slate-50 p-4 font-mono text-xs">
      {children}
    </pre>
  );
}

function Uwaga({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-xl border-l-4 border-[var(--akcent)] bg-[color-mix(in_srgb,var(--akcent)_10%,transparent)] p-3 text-xs">
      {children}
    </p>
  );
}

function Tabela({
  naglowki,
  wyrownanie,
  children,
}: {
  naglowki: string[];
  wyrownanie: ("left" | "right")[];
  children: React.ReactNode;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full text-sm">
        <thead className="tabela-naglowek text-[10px] uppercase tracking-wide text-slate-500">
          <tr>
            {naglowki.map((h, i) => (
              <th
                key={h}
                className={`px-2 py-1.5 ${wyrownanie[i] === "right" ? "text-right" : "text-left"}`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

/** Lista "etykieta: wartosc". Trzeci element pozycji podswietla wartosc. */
function Liczby({
  pozycje,
}: {
  pozycje: (readonly [string, string | number | null, string?])[];
}) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
      {pozycje.map(([etykieta, wartosc, ton]) => (
        <div
          key={etykieta}
          className="wiersz-danych"
        >
          <dt className="text-xs text-slate-500">{etykieta}</dt>
          <dd
            className={`tabular-nums ${
              ton === "uwaga"
                ? "font-semibold text-amber-700 dark:text-amber-400"
                : ""
            }`}
          >
            {wartosc === null
              ? "—"
              : typeof wartosc === "number"
                ? wartosc.toLocaleString("pl-PL")
                : wartosc}
          </dd>
        </div>
      ))}
    </dl>
  );
}
