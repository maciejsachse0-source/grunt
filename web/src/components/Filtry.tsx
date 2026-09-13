"use client";

/**
 * Panel filtrow. Zakres z sekcji 7.2 dokumentu, ograniczony do tego, co system
 * naprawde umie policzyc. Filtry, ktore wymagaja izochron albo klas
 * bonitacyjnych, pojawia sie razem z tymi danymi, a nie wczesniej: filtr, ktory
 * nic nie odsiewa, jest gorszy niz jego brak.
 */

import { useEffect, useState } from "react";
import type { Filtry, Kategorie, RodzajDzialki } from "@/lib/api";
import { NAZWY_RODZAJOW, OPIS_STATUSU, pobierzKategorie } from "@/lib/api";
import { ZapisaneFiltry } from "./ZapisaneFiltry";

const STATUSY = ["A", "B", "C", "E", "D"] as const;
const RODZAJE: RodzajDzialki[] = [
  "mieszkaniowa",
  "uslugowa",
  "przemyslowa",
  "lesna",
];

interface Props {
  filtry: Filtry;
  onChange: (filtry: Filtry) => void;
  liczbaWynikow: number;
}

export function PanelFiltrow({ filtry, onChange, liczbaWynikow }: Props) {
  // Liczby ofert per rodzaj i lista realnie zajetych powiatow i gmin. Bez tego
  // filtr oferowalby kategorie, ktore w bazie nie maja ani jednej oferty.
  const [powiaty, setPowiaty] = useState<Kategorie | null>(null);
  const [gminy, setGminy] = useState<Kategorie | null>(null);

  useEffect(() => {
    let aktualne = true;
    Promise.all([pobierzKategorie("powiat"), pobierzKategorie("gmina")])
      .then(([wPowiatach, wGminach]) => {
        if (!aktualne) return;
        setPowiaty(wPowiatach);
        setGminy(wGminach);
      })
      .catch(() => {
        if (aktualne) {
          setPowiaty(null);
          setGminy(null);
        }
      });
    return () => {
      aktualne = false;
    };
  }, []);

  function ustaw<K extends keyof Filtry>(klucz: K, wartosc: Filtry[K]) {
    const nowe = { ...filtry };
    // Filtr wylaczony usuwamy z obiektu, zamiast wysylac pusta wartosc:
    // dzieki temu ten sam ksztalt trafi pozniej do saved_filters bez smieci.
    const puste =
      wartosc === undefined ||
      wartosc === false ||
      (Array.isArray(wartosc) && wartosc.length === 0);
    if (puste) {
      delete nowe[klucz];
    } else {
      nowe[klucz] = wartosc;
    }
    onChange(nowe);
  }

  function przelaczRodzaj(rodzaj: RodzajDzialki) {
    const obecne = filtry.rodzaj ?? [];
    ustaw(
      "rodzaj",
      obecne.includes(rodzaj)
        ? obecne.filter((r) => r !== rodzaj)
        : [...obecne, rodzaj],
    );
  }

  // W filtrze siedzi jeden kod TERYT: gmina (7 znakow) albo powiat (4).
  const wybranyTeryt = filtry.teryt?.[0] ?? "";
  const wybranyPowiat = wybranyTeryt.slice(0, 4);
  const wybranaGmina = wybranyTeryt.length === 7 ? wybranyTeryt : "";
  const gminyPowiatu = (gminy?.obszary ?? []).filter((o) =>
    wybranyPowiat ? o.teryt.startsWith(wybranyPowiat) : false,
  );

  function przelaczStatus(status: string) {
    const obecne = filtry.status_planistyczny ?? [];
    const nowe = obecne.includes(status)
      ? obecne.filter((s) => s !== status)
      : [...obecne, status];
    ustaw("status_planistyczny", nowe);
  }

  const liczbaAktywnych = Object.keys(filtry).length;

  return (
    <aside className="szklo w-full shrink-0 space-y-5 p-5 text-sm lg:sticky lg:top-6 lg:w-72 lg:self-start">
      <div className="flex items-baseline justify-between">
        <h2 className="font-semibold">Filtry</h2>
        {liczbaAktywnych > 0 && (
          <button
            onClick={() => onChange({})}
            className="rounded-sm px-2 py-0.5 text-xs text-slate-500 transition-colors hover:bg-slate-200 hover:text-slate-900"
          >
            wyczyść ({liczbaAktywnych})
          </button>
        )}
      </div>

      <p className="szklo-lekkie px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
        <strong className="text-sm font-semibold tabular-nums text-slate-900 dark:text-slate-100">
          {liczbaWynikow.toLocaleString("pl-PL")}
        </strong>{" "}
        ofert spełnia warunki
      </p>

      <Sekcja tytul="Cena (zł)">
        <div className="flex gap-2">
          <Liczba
            placeholder="od"
            wartosc={filtry.price_min}
            onChange={(v) => ustaw("price_min", v)}
          />
          <Liczba
            placeholder="do"
            wartosc={filtry.price_max}
            onChange={(v) => ustaw("price_max", v)}
          />
        </div>
      </Sekcja>

      <Sekcja tytul="Powierzchnia (m²)">
        <div className="flex gap-2">
          <Liczba placeholder="od" wartosc={filtry.area_min} onChange={(v) => ustaw("area_min", v)} />
          <Liczba placeholder="do" wartosc={filtry.area_max} onChange={(v) => ustaw("area_max", v)} />
        </div>
      </Sekcja>

      <Sekcja tytul="Cena za m² — maksimum">
        <Liczba
          placeholder="np. 250"
          wartosc={filtry.price_per_m2_max}
          onChange={(v) => ustaw("price_per_m2_max", v)}
        />
      </Sekcja>

      <Sekcja tytul="Rodzaj działki">
        <div className="space-y-1">
          {RODZAJE.map((rodzaj) => {
            const ile = powiaty?.rodzaje.find((r) => r.rodzaj === rodzaj)?.oferty;
            return (
              <label key={rodzaj} className="flex cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={(filtry.rodzaj ?? []).includes(rodzaj)}
                  onChange={() => przelaczRodzaj(rodzaj)}
                />
                <span>{NAZWY_RODZAJOW[rodzaj]}</span>
                {ile !== undefined && (
                  <span className="ml-auto text-xs tabular-nums text-slate-400">
                    {ile.toLocaleString("pl-PL")}
                  </span>
                )}
              </label>
            );
          })}
        </div>
        {powiaty !== null && powiaty.bez_rodzaju > 0 && (
          <p className="mt-1 text-xs text-slate-500">
            {powiaty.bez_rodzaju.toLocaleString("pl-PL")} ofert nie mówi, jaka to działka.
            Zaznaczenie rodzaju je ukryje — brak danych to nie to samo co inna kategoria.
          </p>
        )}
      </Sekcja>

      <Sekcja tytul="Region">
        <select
          value={wybranyPowiat}
          onChange={(e) =>
            ustaw("teryt", e.target.value ? [e.target.value] : undefined)
          }
          className="pole text-sm"
        >
          <option value="">wszystkie powiaty</option>
          {(powiaty?.obszary ?? []).map((o) => (
            <option key={o.teryt} value={o.teryt}>
              {o.nazwa ?? o.teryt} ({o.oferty})
            </option>
          ))}
        </select>

        {wybranyPowiat && gminyPowiatu.length > 0 && (
          <select
            value={wybranaGmina}
            onChange={(e) =>
              ustaw("teryt", [e.target.value || wybranyPowiat])
            }
            className="pole mt-2 text-sm"
          >
            <option value="">cały powiat</option>
            {gminyPowiatu.map((o) => (
              <option key={o.teryt} value={o.teryt}>
                {o.nazwa ?? o.teryt} ({o.oferty})
              </option>
            ))}
          </select>
        )}

        {powiaty !== null && powiaty.bez_regionu > 0 && (
          <p className="mt-1 text-xs text-slate-500">
            {powiaty.bez_regionu.toLocaleString("pl-PL")} ofert nie ma współrzędnych,
            więc nie da się im przypisać gminy.
          </p>
        )}
      </Sekcja>

      <Sekcja tytul="Status planistyczny">
        <div className="space-y-1">
          {STATUSY.map((status) => (
            <label key={status} className="flex cursor-pointer items-start gap-2">
              <input
                type="checkbox"
                checked={(filtry.status_planistyczny ?? []).includes(status)}
                onChange={() => przelaczStatus(status)}
                className="mt-1"
              />
              <span>
                <span className="font-mono font-semibold">{status}</span>{" "}
                <span className="text-xs text-slate-500">{OPIS_STATUSU[status]}</span>
              </span>
            </label>
          ))}
        </div>
      </Sekcja>

      <Sekcja tytul="Koszt doprowadzenia mediów — maksimum (zł)">
        <Liczba
          placeholder="np. 30000"
          wartosc={filtry.media_koszt_max}
          onChange={(v) => ustaw("media_koszt_max", v)}
        />
      </Sekcja>

      <Sekcja tytul="Front działki — minimum (m)">
        <Liczba
          placeholder="np. 18"
          wartosc={filtry.front_min}
          onChange={(v) => ustaw("front_min", v)}
        />
        <p className="mt-1 text-xs text-slate-500">
          Poniżej 18 m przepisy o odległości od granicy utrudniają zabudowę wolnostojącą.
        </p>
      </Sekcja>

      <Sekcja tytul="Ocena">
        <Liczba
          placeholder="score minimum"
          wartosc={filtry.score_min}
          onChange={(v) => ustaw("score_min", v)}
        />
        <label className="mt-2 flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={filtry.exclude_flood ?? false}
            onChange={(e) => ustaw("exclude_flood", e.target.checked || undefined)}
          />
          <span>bez stref zalewowych</span>
        </label>
        <label className="mt-1 flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={filtry.tylko_ocenione ?? false}
            onChange={(e) => ustaw("tylko_ocenione", e.target.checked || undefined)}
          />
          <span>tylko z policzonym score&apos;em</span>
        </label>
        <label className="mt-1 flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={filtry.bez_duplikatow ?? false}
            onChange={(e) => ustaw("bez_duplikatow", e.target.checked || undefined)}
          />
          <span>bez duplikatów</span>
        </label>
        <p className="mt-1 text-xs text-slate-500">
          Ta sama działka bywa wystawiona na kilku portalach. Z takiej grupy zostaje jedna
          oferta, a pozostałe widać na jej karcie razem z rozrzutem cen.
        </p>
      </Sekcja>

      <Sekcja tytul="Zapisane filtry">
        <ZapisaneFiltry filtry={filtry} onWczytaj={onChange} />
      </Sekcja>
    </aside>
  );
}

function Sekcja({ tytul, children }: { tytul: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">{tytul}</h3>
      {children}
    </div>
  );
}

function Liczba({
  wartosc,
  onChange,
  placeholder,
}: {
  wartosc: number | undefined;
  onChange: (v: number | undefined) => void;
  placeholder?: string;
}) {
  return (
    <input
      type="number"
      value={wartosc ?? ""}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
      className="pole text-sm"
    />
  );
}
