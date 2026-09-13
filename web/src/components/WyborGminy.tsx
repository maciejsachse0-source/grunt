"use client";

/**
 * Wybor gminy wewnatrz powiatu albo wojewodztwa i wykres cen dla niej.
 *
 * DLACZEGO GMINA. Wykres cen w czasie ma sens na terenie, ktory jest jednym
 * rynkiem. Powiat nim nie jest: mediana powiatu wejherowskiego to w duzej
 * mierze Wejherowo i Reda, a gmina wiejska po drugiej stronie powiatu ma ceny
 * o rzad wielkosci nizsze i wlasny przebieg w czasie. Usredniony powiat
 * pokazywalby wiec zmiany struktury transakcji, nie zmiany cen.
 *
 * Dlatego gdy tabela stoi na poziomie powiatu albo wojewodztwa, wykres i tak
 * rysujemy dla gminy: domyslnie tej z najwieksza liczba transakcji, bo jej
 * szereg jest najmniej podatny na skoki. Agregat calego obszaru zostaje
 * dostepny w liscie jako punkt odniesienia, ale nie jest domyslem.
 */

import { useEffect, useState } from "react";
import type { CenaRegionu, PoziomObszaru } from "@/lib/api";
import { pobierzCenyRegionow } from "@/lib/api";
import { WykresCen } from "./WykresCen";

interface Props {
  /** TERYT powiatu (4 cyfry) albo wojewodztwa (2 cyfry). */
  rodzic: string;
  poziomRodzica: PoziomObszaru;
  nazwaObszaru: string | null;
  segment: string;
}

/** Gmina z mniejsza liczba transakcji nie ma szans na sensowny szereg kwartalny. */
const MIN_TRANSAKCJI_GMINY = 10;

export function WyborGminy({
  rodzic,
  poziomRodzica,
  nazwaObszaru,
  segment,
}: Props) {
  const [gminy, setGminy] = useState<CenaRegionu[] | null>(null);
  const [wybrana, setWybrana] = useState<string>("");

  useEffect(() => {
    let aktualne = true;
    // Stan ustawiamy wylacznie w callbacku obietnicy, nie w ciele efektu.
    pobierzCenyRegionow({
      poziom: "gmina",
      segment,
      min_n: MIN_TRANSAKCJI_GMINY,
      sort: "transakcje",
      rodzic,
    })
      .then((dane) => {
        if (!aktualne) return;
        setGminy(dane.items);
        // Domyslnie gmina z najwieksza liczba transakcji, czyli pierwsza przy
        // sortowaniu po transakcjach. Gdy zadna nie przechodzi progu, zostaje
        // agregat obszaru, bo lepszy szereg z powiatu niz brak szeregu.
        setWybrana(dane.items[0]?.teryt ?? "");
      })
      .catch(() => {
        if (aktualne) {
          setGminy([]);
          setWybrana("");
        }
      });
    return () => {
      aktualne = false;
    };
  }, [rodzic, segment]);

  if (gminy === null) {
    return <p className="p-3 text-xs text-slate-400">wczytywanie gmin…</p>;
  }

  const gmina = gminy.find((g) => g.teryt === wybrana) ?? null;
  const etykietaObszaru =
    poziomRodzica === "powiat" ? "cały powiat" : "całe województwo";

  return (
    <div className="flex flex-col">
      <div className="flex flex-wrap items-baseline gap-2 px-3 pt-3 text-xs">
        <label className="flex items-center gap-2">
          <span className="uppercase tracking-wide text-slate-500">gmina</span>
          <select
            value={wybrana}
            onChange={(e) => setWybrana(e.target.value)}
            className="pole w-auto py-1 text-xs"
          >
            {gminy.map((g) => (
              <option key={g.teryt} value={g.teryt}>
                {g.nazwa ?? g.teryt} ({g.n.toLocaleString("pl-PL")} transakcji)
              </option>
            ))}
            <option value="">{etykietaObszaru} razem</option>
          </select>
        </label>
        {gminy.length === 0 && (
          <span className="text-slate-500">
            Żadna gmina w tym obszarze nie ma {MIN_TRANSAKCJI_GMINY} transakcji
            w tym rodzaju gruntu — wykres pokazuje {etykietaObszaru}.
          </span>
        )}
        {wybrana === "" && gminy.length > 0 && (
          <span className="text-slate-500">
            Mediana z całego obszaru miesza rynki sąsiednich gmin — do
            porównania, nie do wyciągania wniosków o cenach w jednym miejscu.
          </span>
        )}
      </div>

      <WykresCen
        poziom={wybrana ? "gmina" : poziomRodzica}
        teryt={wybrana || rodzic}
        nazwa={wybrana ? (gmina?.nazwa ?? null) : nazwaObszaru}
        segment={segment}
      />
    </div>
  );
}
