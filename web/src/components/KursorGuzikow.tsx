"use client";

/**
 * Podaje arkuszowi styli miejsce, w ktorym kursor dotknal guzika.
 *
 * Wypelnienie guzika rozrasta sie z punktu wejscia kursora i cofa w strone
 * punktu wyjscia. Sam CSS nie zna polozenia myszy, wiec wspolrzedne wstawiamy
 * do wlasciwosci --x i --y na konkretnym guziku.
 *
 * Trzy decyzje warte odnotowania:
 *
 * 1. Jeden nasluch na dokumencie zamiast procedur obslugi na kazdym guziku.
 *    Guziki powstaja i znikaja razem z widokami, a delegacja nie musi o tym
 *    wiedziec i nie wymaga dotykania miejsc wywolania.
 * 2. Zadnego nasluchu ciaglego ruchu. pointerover i pointerout niosa juz
 *    clientX i clientY, a to jedyne dwa momenty, ktore maja znaczenie: poczatek
 *    i koniec najechania. Ruch w srodku guzika niczego nie zmienia, bo kolo
 *    jest wtedy i tak rozciagniete ponad krawedzie.
 * 3. pointerdown jest tu dla dotyku. Palec nie generuje pointerover przed
 *    stuknieciem, wiec bez tego wypelnienie szloby ze srodka zamiast z miejsca
 *    dotkniecia.
 */

import { useEffect } from "react";

const GUZIKI = ".przycisk, .przycisk-glowny, .zakladka";

export function KursorGuzikow() {
  useEffect(() => {
    const ustawPunkt = (zdarzenie: PointerEvent) => {
      const cel = (zdarzenie.target as Element | null)?.closest?.(GUZIKI);
      if (!(cel instanceof HTMLElement)) return;

      // pointerover i pointerout odpalaja sie takze przy przechodzeniu miedzy
      // guzikiem a jego wlasnym wnetrzem, na przyklad strzalka w pastylce CTA.
      // Gdyby to przepuscic, srodek kola przeskakiwalby w polowie najechania.
      const powiazany = zdarzenie.relatedTarget;
      if (powiazany instanceof Node && cel.contains(powiazany)) return;

      const ramka = cel.getBoundingClientRect();
      if (ramka.width === 0 || ramka.height === 0) return;

      const x = ((zdarzenie.clientX - ramka.left) / ramka.width) * 100;
      const y = ((zdarzenie.clientY - ramka.top) / ramka.height) * 100;
      cel.style.setProperty("--x", `${x.toFixed(1)}%`);
      cel.style.setProperty("--y", `${y.toFixed(1)}%`);
    };

    const opcje: AddEventListenerOptions = { passive: true, capture: true };
    document.addEventListener("pointerover", ustawPunkt, opcje);
    document.addEventListener("pointerout", ustawPunkt, opcje);
    document.addEventListener("pointerdown", ustawPunkt, opcje);

    return () => {
      document.removeEventListener("pointerover", ustawPunkt, opcje);
      document.removeEventListener("pointerout", ustawPunkt, opcje);
      document.removeEventListener("pointerdown", ustawPunkt, opcje);
    };
  }, []);

  return null;
}
