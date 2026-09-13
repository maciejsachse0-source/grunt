"use client";

/**
 * Zapis oferty do obserwowanych: status, notatka, ocena. Sekcja 7.3 dokumentu.
 *
 * Zapisujemy oferte, a nie dzialke ewidencyjna, bo pewne dopasowanie do dzialki
 * mamy tylko dla czesci ofert, a zapisac chce sie to, co sie wlasnie oglada.
 *
 * Notatka zapisuje sie na wyjsciu z pola, nie przy kazdym znaku: pisanie
 * notatki nie ma generowac zapytania na litere.
 */

import { useEffect, useState } from "react";
import type { StatusZapisu, ZapisanaOferta } from "@/lib/api";
import { STATUSY_ZAPISU, ocenOferte, pobierzZapisane, usunZapis, zapiszOferte } from "@/lib/api";

interface Props {
  id: number;
  onZmiana?: () => void;
}

export function ZapisOferty({ id, onZmiana }: Props) {
  const [zapis, setZapis] = useState<ZapisanaOferta | null>(null);
  const [notatka, setNotatka] = useState("");
  const [stan, setStan] = useState<"wczytywanie" | "gotowe" | "zapisywanie">("wczytywanie");
  const [blad, setBlad] = useState<string | null>(null);

  useEffect(() => {
    let aktualne = true;
    pobierzZapisane()
      .then((dane) => {
        if (!aktualne) return;
        const znaleziony = dane.items.find((o) => o.id === id) ?? null;
        setZapis(znaleziony);
        setNotatka(znaleziony?.note ?? "");
        setStan("gotowe");
      })
      .catch(() => aktualne && setStan("gotowe"));
    return () => {
      aktualne = false;
    };
  }, [id]);

  async function zapisz(zmiana: { status?: StatusZapisu; note?: string | null }) {
    setStan("zapisywanie");
    setBlad(null);
    try {
      const status = zmiana.status ?? zapis?.status ?? "obserwuje";
      const note = zmiana.note !== undefined ? zmiana.note : notatka || null;
      await zapiszOferte(id, { status, note });
      const dane = await pobierzZapisane();
      setZapis(dane.items.find((o) => o.id === id) ?? null);
      onZmiana?.();
    } catch (e) {
      setBlad(String(e));
    } finally {
      setStan("gotowe");
    }
  }

  async function usun() {
    setStan("zapisywanie");
    try {
      await usunZapis(id);
      setZapis(null);
      setNotatka("");
      onZmiana?.();
    } catch (e) {
      setBlad(String(e));
    } finally {
      setStan("gotowe");
    }
  }

  async function ocen(verdict: -1 | 1) {
    try {
      await ocenOferte(id, verdict);
      const dane = await pobierzZapisane();
      setZapis(dane.items.find((o) => o.id === id) ?? null);
    } catch (e) {
      setBlad(String(e));
    }
  }

  if (stan === "wczytywanie") {
    return <p className="text-xs text-slate-400">…</p>;
  }

  if (!zapis) {
    return (
      <div>
        <button
          onClick={() => zapisz({ status: "obserwuje" })}
          className="przycisk w-full"
        >
          ☆ Obserwuj tę ofertę
        </button>
        {blad && <p className="mt-1 text-xs text-red-600">{blad}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-sm">★ obserwowana</span>
        <select
          value={zapis.status}
          onChange={(e) => zapisz({ status: e.target.value as StatusZapisu })}
          className="pole w-auto py-1 text-xs"
        >
          {STATUSY_ZAPISU.map((s) => (
            <option key={s.wartosc} value={s.wartosc}>
              {s.etykieta}
            </option>
          ))}
        </select>
        <button
          onClick={usun}
          className="ml-auto rounded-sm px-2 py-0.5 text-xs text-slate-500 transition-colors hover:bg-rose-200/50 hover:text-rose-700"
        >
          usuń
        </button>
      </div>

      <textarea
        value={notatka}
        onChange={(e) => setNotatka(e.target.value)}
        onBlur={() => notatka !== (zapis.note ?? "") && zapisz({ note: notatka || null })}
        placeholder="Notatka: co sprawdzić, z kim rozmawiać, czego brakuje"
        rows={3}
        className="pole text-xs"
      />

      <div className="flex items-center gap-2 text-xs">
        <span className="text-slate-500">Twoja ocena:</span>
        <button
          onClick={() => ocen(1)}
          className={`rounded-sm border px-3 py-0.5 transition-colors ${
            zapis.ocena === 1
              ? "border-emerald-600 bg-emerald-200/50 text-emerald-700"
              : "border-slate-300 bg-white text-slate-500 hover:border-slate-900 hover:text-slate-900"
          }`}
        >
          dobra
        </button>
        <button
          onClick={() => ocen(-1)}
          className={`rounded-sm border px-3 py-0.5 transition-colors ${
            zapis.ocena === -1
              ? "border-rose-600 bg-rose-200/50 text-rose-700"
              : "border-slate-300 bg-white text-slate-500 hover:border-slate-900 hover:text-slate-900"
          }`}
        >
          słaba
        </button>
        {/* Oceny sa materialem na kalibracje z sekcji 5.6, a nie ozdoba */}
        <span className="ml-auto text-slate-400">{stan === "zapisywanie" ? "zapisuję…" : ""}</span>
      </div>

      {blad && <p className="text-xs text-red-600">{blad}</p>}
    </div>
  );
}
