"use client";

/**
 * Zapisane filtry z alertem. Sekcja 7.4 dokumentu.
 *
 * Zapisany filtr to dokladnie ten sam obiekt, ktory idzie do listy ofert.
 * Dzieki temu alert nie moze pokazac czegos innego niz lista: worker sklada
 * z niego to samo zapytanie.
 *
 * Pierwszy przebieg alertu po wlaczeniu niczego nie wysyla, tylko zapamietuje
 * biezace trafienia. Inaczej wlaczenie alertu na istniejacej bazie oznaczaloby
 * kilkadziesiat powiadomien naraz. Interfejs musi to powiedziec wprost, zeby
 * cisza po wlaczeniu nie wygladala na awarie.
 */

import { useEffect, useState } from "react";
import type { Filtry, ZapisanyFiltr } from "@/lib/api";
import { pobierzFiltry, usunFiltr, zapiszFiltr, zmienFiltr } from "@/lib/api";

interface Props {
  filtry: Filtry;
  onWczytaj: (filtry: Filtry) => void;
}

export function ZapisaneFiltry({ filtry, onWczytaj }: Props) {
  const [zapisane, setZapisane] = useState<ZapisanyFiltr[]>([]);
  const [nazwa, setNazwa] = useState("");
  const [blad, setBlad] = useState<string | null>(null);

  function odswiez() {
    pobierzFiltry()
      .then((dane) => setZapisane(dane.items))
      .catch((e) => setBlad(String(e)));
  }

  useEffect(odswiez, []);

  const liczbaWarunkow = Object.keys(filtry).length;

  async function zapisz() {
    if (!nazwa.trim()) return;
    setBlad(null);
    try {
      await zapiszFiltr(nazwa.trim(), filtry, false);
      setNazwa("");
      odswiez();
    } catch (e) {
      setBlad(String(e));
    }
  }

  async function przelaczAlert(filtr: ZapisanyFiltr) {
    try {
      await zmienFiltr(filtr.id, { alert_enabled: !filtr.alert_enabled });
      odswiez();
    } catch (e) {
      setBlad(String(e));
    }
  }

  return (
    <div>
      <div className="flex gap-2">
        <input
          value={nazwa}
          onChange={(e) => setNazwa(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && zapisz()}
          placeholder="nazwa filtru"
          className="pole min-w-0 flex-1 text-xs"
        />
        <button
          onClick={zapisz}
          disabled={!nazwa.trim() || liczbaWarunkow === 0}
          className="przycisk shrink-0 px-3 py-1.5"
        >
          zapisz
        </button>
      </div>
      {liczbaWarunkow === 0 && (
        <p className="mt-1 text-xs text-slate-500">
          Ustaw najpierw warunki. Pusty filtr pasowałby do wszystkiego.
        </p>
      )}

      {zapisane.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {zapisane.map((filtr) => (
            <li key={filtr.id} className="szklo-lekkie p-2.5">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => onWczytaj(filtr.filter)}
                  className="min-w-0 flex-1 truncate text-left text-xs underline"
                  title="wczytaj ten filtr"
                >
                  {filtr.name}
                </button>
                <button
                  onClick={() => usunFiltr(filtr.id).then(odswiez)}
                  className="rounded-sm px-1.5 text-xs text-slate-400 transition-colors hover:bg-rose-200/50 hover:text-rose-700"
                  title="usuń filtr"
                >
                  ✕
                </button>
              </div>
              <label className="mt-1 flex cursor-pointer items-center gap-2 text-xs text-slate-500">
                <input
                  type="checkbox"
                  checked={filtr.alert_enabled}
                  onChange={() => przelaczAlert(filtr)}
                />
                <span>alert na Telegram</span>
                {filtr.wyslane > 0 && <span className="ml-auto">{filtr.wyslane} wysłanych</span>}
              </label>
              {filtr.alert_enabled && filtr.last_alert_at === null && (
                <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
                  Pierwszy przebieg zapamięta obecne trafienia i nie wyśle nic. Alerty przyjdą
                  dopiero o nowych ofertach.
                </p>
              )}
            </li>
          ))}
        </ul>
      )}

      {blad && <p className="mt-1 text-xs text-red-600">{blad}</p>}
    </div>
  );
}
