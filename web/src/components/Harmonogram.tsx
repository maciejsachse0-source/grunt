"use client";

/**
 * Zakladka "kiedy pobieramy": rytm zbierania ofert ze wszystkich portali.
 *
 * Kazda inna zakladka pokazuje WYNIK zbierania danych. Ta pokazuje jego RYTM,
 * bo od niego zalezy, czy patrzysz na rynek sprzed godziny, czy sprzed tygodnia.
 *
 * Wszystkie liczby przychodza z /api/harmonogram, ktory czyta je z kodu
 * (interwaly z jobs/scheduler.py, limity stron z adapterow, odstepy z konfiguracji)
 * i z tabeli jobs. Nic nie jest tu przepisane recznie, wiec zmiana interwalu
 * w kodzie zmienia te strone od razu.
 *
 * Dwie rzeczy strona mowi wprost, bo bez nich liczby myla:
 * harmonogram liczy sie od OSTATNIEGO UDANEGO przebiegu, a nie od pelnej godziny,
 * i nie dzieje sie nic, dopoki nie chodzi worker.
 */

import { useEffect, useState } from "react";
import type {
  Harmonogram as Dane,
  PortalHarmonogram,
  PrzebiegPortalu,
} from "@/lib/api";
import { format, pobierzHarmonogram } from "@/lib/api";

export function Harmonogram() {
  const [dane, setDane] = useState<Dane | null>(null);
  const [blad, setBlad] = useState<string | null>(null);

  useEffect(() => {
    let aktualne = true;
    pobierzHarmonogram()
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
        Nie udało się pobrać harmonogramu: {blad}
      </p>
    );
  }
  if (!dane) return <p className="p-4 text-sm text-slate-400">wczytywanie…</p>;

  const { worker, scrape, portale, zadania, zasady } = dane;
  const wlaczonych = portale.filter((p) => p.wlaczony && !p.bez_adaptera);

  return (
    <div className="flex max-w-4xl flex-col gap-5 text-sm leading-relaxed">
      {/* --------------------------------------------------- odpowiedz wprost */}
      <section className="szklo px-6 py-5">
        <h2 className="text-lg font-semibold tracking-tight">
          Kiedy pobierane są nowe oferty
        </h2>
        <p className="mt-2 text-slate-600 dark:text-slate-300">
          Co <strong>{format.czas(scrape.co_ile_godzin)}</strong> rusza jeden
          przebieg, który obchodzi po kolei{" "}
          <strong>wszystkie {wlaczonych.length} włączone portale</strong>. Nie ma
          osobnych harmonogramów dla poszczególnych stron: albo pobierane są
          wszystkie, albo żadna.
        </p>
        <p className="mt-2 text-slate-600 dark:text-slate-300">
          Harmonogram nie jest zegarem ściennym. Zadanie staje się wymagalne po
          upływie interwału <em>od ostatniego udanego przebiegu</em>, więc godziny
          przebiegów przesuwają się po każdej dłuższej przerwie.
        </p>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <Kafel
            etykieta="ostatni przebieg"
            wartosc={format.dataGodzina(scrape.ostatni)}
          />
          <Kafel
            etykieta="następny przebieg"
            wartosc={
              scrape.w_kolejce
                ? "czeka w kolejce"
                : scrape.nastepny
                  ? format.dataGodzina(scrape.nastepny)
                  : "przy najbliższym obrocie"
            }
            dopisek={
              scrape.za_ile_godzin !== null
                ? `za ${format.czas(scrape.za_ile_godzin)}`
                : "termin już minął"
            }
          />
          <Kafel etykieta="co ile" wartosc={format.czas(scrape.co_ile_godzin)} />
        </div>

        {!worker.prawdopodobnie_chodzi && (
          <p className="mt-4 rounded-xl border-l-4 border-amber-500 bg-amber-500/10 p-3 text-xs">
            <strong>Uwaga: worker prawdopodobnie nie chodzi.</strong> Ostatnie
            zadanie skończyło się {format.dataGodzina(worker.ostatnie_zadanie)}
            {worker.cisza_minut !== null && (
              <>
                , czyli {format.czas(worker.cisza_minut / 60)} temu, przy progu{" "}
                {format.czas(worker.prog_ciszy_minut / 60)}
              </>
            )}
            . Dopóki proces nie działa, harmonogram jest tylko planem: nic się nie
            pobiera i nie ma o tym żadnego błędu.{" "}
            <code>{worker.jak_uruchomic}</code>
          </p>
        )}
      </section>

      {/* ------------------------------------------------------------ PORTALE */}
      <Sekcja
        tytul="1. Portal po portalu"
        podtytul="skąd startuje przebieg, ile stron obchodzi i co ostatnio przyniósł"
      >
        <Tabela
          naglowki={[
            "portal",
            "adresów × stron",
            "ofert w bazie",
            "nowych 24 h",
            "nowych 7 dni",
            "ostatnia nowa oferta",
          ]}
          wyrownanie={["left", "right", "right", "right", "right", "left"]}
        >
          {portale.map((p) => (
            <tr key={p.portal} className="wiersz-statyczny">
              <td className="px-2 py-1.5">
                <span className="font-mono text-xs">{p.portal}</span>
                {!p.wlaczony && (
                  <span className="ml-1 text-[10px] uppercase text-slate-500">
                    wyłączony
                  </span>
                )}
                {p.bez_adaptera && (
                  <span className="ml-1 text-[10px] uppercase text-amber-700 dark:text-amber-400">
                    brak adaptera
                  </span>
                )}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">
                {p.bez_adaptera
                  ? "—"
                  : `${p.adresow_startowych} × ${p.maks_stron_na_adres}`}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">
                {p.ofert_w_bazie.toLocaleString("pl-PL")}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">
                {p.nowych_24h.toLocaleString("pl-PL")}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">
                {p.nowych_7d.toLocaleString("pl-PL")}
              </td>
              <td className="px-2 py-1.5 text-xs">
                {p.ostatnia_nowa ? (
                  format.dataGodzina(p.ostatnia_nowa)
                ) : (
                  <span className="text-amber-700 dark:text-amber-400">
                    nigdy
                  </span>
                )}
              </td>
            </tr>
          ))}
        </Tabela>
        <p className="text-xs text-slate-500">
          „Adresów × stron” to zasięg jednego przebiegu: ile adresów startowych ma
          portal (Morizon i Gratka pytają osobno o każdy powiat, Otodom jednym
          adresem wojewódzkim) i do której strony wyników wolno zejść. Limit 10
          stron u Morizona i Gratki bierze się wprost z ich robots.txt, nie z
          naszej decyzji. U Otodomu robots.txt nie stawia granicy i limit jest
          nasz własny — z higieny scrapingu, nie z zakazu.
        </p>

        {portale.some((p) => p.ostatni_przebieg) && (
          <>
            <h4 className="pt-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Ostatni udany przebieg, portal po portalu
            </h4>
            <Tabela
              naglowki={[
                "portal",
                "stron",
                "ofert na listingu",
                "nowe",
                "zmienione",
                "pobrane detale",
                "błędy",
              ]}
              wyrownanie={[
                "left",
                "right",
                "right",
                "right",
                "right",
                "right",
                "right",
              ]}
            >
              {portale
                .filter(
                  (p): p is PortalHarmonogram & { ostatni_przebieg: PrzebiegPortalu } =>
                    p.ostatni_przebieg !== null,
                )
                .map((p) => (
                  <tr key={p.portal} className="wiersz-statyczny">
                    <td className="px-2 py-1.5 font-mono text-xs">{p.portal}</td>
                    <Komorka wartosc={p.ostatni_przebieg.stron_wynikow} />
                    <Komorka wartosc={p.ostatni_przebieg.ofert_na_listingu} />
                    <Komorka wartosc={p.ostatni_przebieg.nowe} />
                    <Komorka wartosc={p.ostatni_przebieg.zmienione} />
                    <Komorka wartosc={p.ostatni_przebieg.pobrane_detale} />
                    <td
                      className={`px-2 py-1.5 text-right tabular-nums ${
                        p.ostatni_przebieg.bledy.length
                          ? "text-amber-700 dark:text-amber-400"
                          : ""
                      }`}
                    >
                      {p.ostatni_przebieg.bledy.length}
                    </td>
                  </tr>
                ))}
            </Tabela>
            <p className="text-xs text-slate-500">
              Portal bez wiersza w tej tabeli nie brał udziału w ostatnim udanym
              przebiegu — jego oferty pochodzą z wcześniejszego uruchomienia
              ręcznego. Różnica między „ofert na listingu” a „pobrane detale” to
              cała oszczędność strategii DIFF: strona oferty schodzi tylko dla
              pozycji nowych i zmienionych.
            </p>
          </>
        )}
      </Sekcja>

      {/* --------------------------------------------------------- PRZEBIEGI */}
      <Sekcja
        tytul="2. Ostatnie przebiegi"
        podtytul="historia zadania scrape z kolejki jobs"
      >
        {scrape.przebiegi.length === 0 ? (
          <p className="text-xs text-slate-500">
            Kolejka nie ma jeszcze ani jednego przebiegu scrape. Oferty w bazie
            pochodzą z ręcznych uruchomień <code>scripts/scrape.py</code>.
          </p>
        ) : (
          <Tabela
            naglowki={["start", "koniec", "trwało", "status", "portale"]}
            wyrownanie={["left", "left", "right", "left", "left"]}
          >
            {scrape.przebiegi.map((p) => (
              <tr key={p.id} className="wiersz-statyczny">
                <td className="px-2 py-1.5 text-xs">
                  {format.dataGodzina(p.start)}
                </td>
                <td className="px-2 py-1.5 text-xs">
                  {format.dataGodzina(p.koniec)}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  {p.trwalo_minut === null
                    ? "—"
                    : `${p.trwalo_minut.toLocaleString("pl-PL")} min`}
                </td>
                <td
                  className={`px-2 py-1.5 text-xs ${
                    p.status === "done"
                      ? ""
                      : "text-red-700 dark:text-red-400"
                  }`}
                >
                  {p.status}
                  {p.prob > 1 && ` (prób: ${p.prob})`}
                </td>
                <td className="px-2 py-1.5 text-xs">
                  {p.portale.length
                    ? p.portale
                        .map((s) => `${s.portal}: +${s.nowe}`)
                        .join(", ")
                    : "—"}
                </td>
              </tr>
            ))}
          </Tabela>
        )}
        <p className="text-xs text-slate-500">{scrape.strategia}</p>
        <p className="text-xs text-slate-500">{scrape.dlaczego_tyle}</p>
      </Sekcja>

      {/* ----------------------------------------------------------- ZADANIA */}
      <Sekcja
        tytul="3. Cały harmonogram"
        podtytul="pobranie oferty to dopiero pierwszy krok, reszta dzieje się później"
      >
        <Tabela
          naglowki={["zadanie", "co robi", "co ile", "ostatnio", "następnie"]}
          wyrownanie={["left", "left", "right", "left", "left"]}
        >
          {zadania.map((z) => (
            <tr
              key={z.kind}
              className={`wiersz-statyczny ${z.kind === "scrape" ? "font-medium" : ""}`}
            >
              <td className="px-2 py-1.5 font-mono text-xs">{z.kind}</td>
              <td className="px-2 py-1.5 text-xs">{z.opis}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">
                {format.czas(z.co_ile_godzin)}
              </td>
              <td className="px-2 py-1.5 text-xs">
                {z.ostatnie ? (
                  format.dataGodzina(z.ostatnie)
                ) : (
                  <span className="text-amber-700 dark:text-amber-400">
                    nigdy
                  </span>
                )}
              </td>
              <td className="px-2 py-1.5 text-xs">
                {z.w_kolejce ? (
                  <span className="text-emerald-700 dark:text-emerald-400">
                    czeka w kolejce
                  </span>
                ) : z.za_ile_godzin !== null ? (
                  `za ${format.czas(z.za_ile_godzin)}`
                ) : (
                  <span className="text-amber-700 dark:text-amber-400">
                    termin minął
                  </span>
                )}
              </td>
            </tr>
          ))}
        </Tabela>
        <p className="text-xs text-slate-500">
          Oferta pobrana o północy nie ma jeszcze ani danych publicznych, ani
          oceny. Dane z GUGiK dokłada zadanie <code>enrich</code> porcjami po{" "}
          {String(
            zadania.find((z) => z.kind === "enrich")?.payload?.limit ?? "?",
          )}{" "}
          ofert na godzinę, a score liczy się osobno co{" "}
          {format.czas(
            zadania.find((z) => z.kind === "score")?.co_ile_godzin ?? null,
          )}
          . Świeża oferta pojawia się więc na liście od razu, ale z pełną oceną
          dopiero po tych krokach.
        </p>
      </Sekcja>

      {/* ------------------------------------------------------------ KOLEJKA */}
      <Sekcja
        tytul="4. Worker i kolejka"
        podtytul="jeden proces, który to wszystko wykonuje"
      >
        <p className="text-xs text-slate-500">{worker.opis}</p>
        <Liczby
          pozycje={[
            [
              "stan workera",
              worker.prawdopodobnie_chodzi ? "chodzi" : "cisza",
              worker.prawdopodobnie_chodzi ? undefined : "uwaga",
            ],
            ["ostatnie zadanie", format.dataGodzina(worker.ostatnie_zadanie)],
            ["czeka w kolejce", worker.kolejka.czeka],
            ["w trakcie", worker.kolejka.w_trakcie],
            [
              "nieudanych",
              worker.kolejka.nieudane,
              worker.kolejka.nieudane ? "uwaga" : undefined,
            ],
            ["zakończonych", worker.kolejka.zakonczone],
          ]}
        />
        <p className="text-xs text-slate-500">
          Stan workera jest domysłem z ciszy w kolejce, a nie odczytem z procesu:
          najkrótszy interwał w harmonogramie to godzina, więc żywy worker kończy
          jakieś zadanie przynajmniej raz na{" "}
          {format.czas(worker.prog_ciszy_minut / 60)}. Historia zadań starsza niż
          30 dni jest kasowana, więc licznik „zakończonych” to ostatni miesiąc.
        </p>
      </Sekcja>

      {/* ------------------------------------------------------------ ZASADY */}
      <Sekcja
        tytul="5. Zasady, których przebieg pilnuje"
        podtytul="higiena scrapingu — dlaczego nie pobieramy częściej"
      >
        <Liczby
          pozycje={[
            ["odstęp między żądaniami", `${zasady.odstep_s} s`],
            ["limit stron na przebieg", zasady.maks_stron_na_przebieg],
            ["oferta wygasa po", `${zasady.wygaszenie_po_dniach} dniach`],
            ["region", `TERYT ${zasady.region_teryt}`],
            ["ponowień zadania", zasady.maks_prob],
            [
              "backoff",
              zasady.backoff_minut.map((m) => `${m} min`).join(" → "),
            ],
          ]}
        />
        <ul className="flex list-disc flex-col gap-1.5 pl-5 text-xs text-slate-600 dark:text-slate-300">
          {zasady.punkty.map((punkt) => (
            <li key={punkt}>{punkt}</li>
          ))}
        </ul>
        <p className="text-xs text-slate-500">
          Nagłówek, którym się przedstawiamy: <code>{zasady.user_agent}</code>
        </p>
      </Sekcja>
    </div>
  );
}

/* ------------------------------------------------------------- kawalki UI */

function Kafel({
  etykieta,
  wartosc,
  dopisek,
}: {
  etykieta: string;
  wartosc: string;
  dopisek?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">
        {etykieta}
      </div>
      <div className="text-sm font-medium tabular-nums">{wartosc}</div>
      {dopisek && (
        <div className="text-[11px] text-slate-500">{dopisek}</div>
      )}
    </div>
  );
}

function Komorka({ wartosc }: { wartosc: number }) {
  return (
    <td className="px-2 py-1.5 text-right tabular-nums">
      {wartosc.toLocaleString("pl-PL")}
    </td>
  );
}

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
        <div key={etykieta} className="wiersz-danych">
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
