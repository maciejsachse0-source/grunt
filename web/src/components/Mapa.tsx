"use client";

/**
 * Mapa ofert. MapLibre GL, podklad z rastrowych kafli OpenStreetMap.
 *
 * Dokument (sekcja 4.2) przewiduje docelowo wlasne kafle PMTiles, zeby nie
 * zalezec od cudzego serwera i nie obciazac go ruchem. Do prywatnego narzedzia
 * o kilkuset ofertach rastrowy OSM z podana atrybucja wystarcza, a przejscie
 * na PMTiles to podmiana jednego obiektu style.
 *
 * Kolor punktu niesie informacje: zielony to wysoki score, szary to brak
 * wyniku. Punkt bez score'u NIE jest rysowany jako "zero", bo to sugerowaloby
 * ocene, ktorej nie ma.
 *
 * WYBOR OFERTY (sekcja "Mapa i obrys dzialki" w CLAUDE.md)
 * Klikniecie wiersza w tabeli albo punktu na mapie przybliza mape do oferty
 * dwuetapowo: najpierw skok do punktu, ktory mapa juz ma w pamieci, potem
 * kadr na obrysie dzialki, gdy ten przyjdzie z API. Dzieki temu reakcja jest
 * natychmiastowa, a nie po rundzie do serwera.
 *
 * PINEZKA JEST ZAWSZE, OBRYS TYLKO GDY DZIALKA JEST PEWNA
 * Kazda wybrana oferta dostaje pinezke we wspolrzednych z ogloszenia. Obrys
 * dochodzi do niej tylko przy dopasowaniu high albo medium, czyli wtedy, gdy
 * powierzchnia dzialki zgadza sie z ogloszeniem (enrich/match_parcel.py).
 * Przy dopasowaniu low powierzchnia sie NIE zgadza, wiec geometria pod punktem
 * to zwykle sasiad albo dzialka-matka: narysowanie jej byloby pokazaniem
 * cudzego gruntu jako przedmiotu oferty. Wtedy zostaje sama pinezka i podpis
 * mowiacy wprost, czego nie wiemy.
 */

import { useCallback, useEffect, useRef, useState } from "react";
// MapLibre GL 6 nie ma juz eksportu domyslnego, wszystko idzie przez nazwy
import {
  LngLatBounds,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  type GeoJSONSource,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { pobierzObrys, type ObrysDzialki } from "@/lib/api";

interface Props {
  geojson: GeoJSON.FeatureCollection | null;
  wybrana: number | null;
  onWybierz: (id: number) => void;
}

const STYL: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap",
      maxzoom: 19,
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

const PUSTA: GeoJSON.FeatureCollection = {
  type: "FeatureCollection",
  features: [],
};

const AKCENT = "#c2481a";

/** Dopasowania, przy ktorych wolno narysowac obrys jako obrys TEJ oferty. */
const PEWNE = new Set(["high", "medium"]);

export function Mapa({ geojson, wybrana, onWybierz }: Props) {
  const kontener = useRef<HTMLDivElement>(null);
  const mapa = useRef<MapLibreMap | null>(null);
  const gotowa = useRef(false);
  // Kolekcje i wybor trzymamy takze w ref, bo efekt wyboru nie moze zalezec od
  // geojsona: przeladowanie listy (inna strona, inne sortowanie) przestawialoby
  // wtedy kadr mapy pod uzytkownikiem.
  const kolekcja = useRef<GeoJSON.FeatureCollection | null>(null);
  const wybor = useRef<number | null>(null);
  const zadanie = useRef(0);
  const zapamietane = useRef(new Map<number, ObrysDzialki>());
  const pinezka = useRef<Marker | null>(null);
  const [opisObrysu, setOpisObrysu] = useState<ObrysDzialki | null>(null);

  /** Pinezka jest jedna: przy zmianie oferty przenosimy ja, nie mnozymy. */
  const postawPinezke = useCallback((lon: number, lat: number) => {
    const m = mapa.current;
    if (!m) return;
    if (pinezka.current) {
      pinezka.current.setLngLat([lon, lat]);
      return;
    }
    pinezka.current = new Marker({ color: AKCENT })
      .setLngLat([lon, lat])
      .addTo(m);
  }, []);

  const zdejmijPinezke = useCallback(() => {
    pinezka.current?.remove();
    pinezka.current = null;
  }, []);

  useEffect(() => {
    if (!kontener.current || mapa.current) return;

    mapa.current = new MapLibreMap({
      container: kontener.current,
      style: STYL,
      center: [18.2, 54.2], // pomorskie
      zoom: 7.5,
      attributionControl: { compact: true },
    });
    mapa.current.addControl(new NavigationControl(), "top-right");

    mapa.current.on("load", () => {
      const m = mapa.current!;
      // Zrodlo wyboru idzie pierwsze, zeby obrys dzialki lezal POD punktami
      // ofert. Odwrotna kolejnosc zaslanialaby klikalny punkt wypelnieniem.
      m.addSource("wybor", { type: "geojson", data: PUSTA });
      m.addSource("oferty", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      m.addLayer({
        id: "dzialka-wypelnienie",
        type: "fill",
        source: "wybor",
        paint: { "fill-color": AKCENT, "fill-opacity": 0.18 },
      });
      m.addLayer({
        id: "dzialka-obrys",
        type: "line",
        source: "wybor",
        paint: { "line-color": AKCENT, "line-width": 2.5 },
      });

      m.addLayer({
        id: "oferty-punkty",
        type: "circle",
        source: "oferty",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 4, 14, 9],
          "circle-color": [
            "case",
            ["==", ["get", "score"], null],
            "#9a938a",
            [">=", ["get", "score"], 70],
            "#0f8f64",
            [">=", ["get", "score"], 50],
            "#0f5f89",
            "#c98f2a",
          ],
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "#ffffff",
          "circle-opacity": 0.9,
        },
      });

      m.on("click", "oferty-punkty", (e) => {
        const cecha = e.features?.[0];
        if (cecha?.id !== undefined) onWybierz(Number(cecha.id));
      });
      m.on("mouseenter", "oferty-punkty", () => {
        m.getCanvas().style.cursor = "pointer";
      });
      m.on("mouseleave", "oferty-punkty", () => {
        m.getCanvas().style.cursor = "";
      });

      gotowa.current = true;
    });

    return () => {
      pinezka.current?.remove();
      pinezka.current = null;
      mapa.current?.remove();
      mapa.current = null;
      gotowa.current = false;
    };
  }, [onWybierz]);

  useEffect(() => {
    const m = mapa.current;
    if (!m || !geojson) return;
    kolekcja.current = geojson;

    const zaladuj = () => {
      const zrodlo = m.getSource("oferty") as GeoJSONSource | undefined;
      if (!zrodlo) return;
      zrodlo.setData(geojson);

      // Kadr ustawia sie do calego wyniku tylko wtedy, gdy uzytkownik nie
      // oglada konkretnej dzialki. Inaczej zmiana strony listy odrzucalaby go
      // od obrysu, ktory wlasnie przyblizyl.
      if (geojson.features.length > 0 && wybor.current === null) {
        const granice = new LngLatBounds();
        for (const cecha of geojson.features) {
          if (cecha.geometry.type === "Point") {
            granice.extend(cecha.geometry.coordinates as [number, number]);
          }
        }
        m.fitBounds(granice, { padding: 40, maxZoom: 13, duration: 400 });
      }
    };

    if (gotowa.current) zaladuj();
    else m.once("idle", zaladuj);
  }, [geojson]);

  // Rysowanie obrysu i kadrowanie. Osobno od pinezki, bo pinezka jest
  // natychmiastowa, a obrys wymaga zapytania.
  const pokazObrys = useCallback(
    (dane: ObrysDzialki) => {
      const m = mapa.current;
      if (!m) return;
      const zrodlo = m.getSource("wybor") as GeoJSONSource | undefined;
      if (!zrodlo) return;

      if (dane.punkt) postawPinezke(dane.punkt.lon, dane.punkt.lat);
      setOpisObrysu(dane);

      const rysujObrys = Boolean(
        dane.obrys && dane.pewnosc && PEWNE.has(dane.pewnosc),
      );

      zrodlo.setData(
        rysujObrys
          ? { type: "FeatureCollection", features: [dane.obrys!] }
          : PUSTA,
      );

      if (rysujObrys && dane.bbox) {
        const [zachod, poludnie, wschod, polnoc] = dane.bbox;
        m.fitBounds(new LngLatBounds([zachod, poludnie], [wschod, polnoc]), {
          // maxZoom nizej niz maksimum kafli OSM: przy 19 podklad jest juz sama
          // szara plama i obrys wisi w prozni.
          padding: 56,
          maxZoom: 17.5,
          duration: 700,
        });
      } else if (dane.punkt) {
        // Bez pewnego obrysu nie udajemy precyzji kadrem: zoom 16 pokazuje
        // okolice pinezki, a nie sugeruje granic, ktorych nie znamy.
        m.flyTo({
          center: [dane.punkt.lon, dane.punkt.lat],
          zoom: 16,
          duration: 700,
        });
      }
    },
    [postawPinezke],
  );

  useEffect(() => {
    wybor.current = wybrana;
    const m = mapa.current;
    if (!m) return;

    const zastosuj = () => {
      if (wybrana === null) {
        (m.getSource("wybor") as GeoJSONSource | undefined)?.setData(PUSTA);
        zdejmijPinezke();
        setOpisObrysu(null);
        return;
      }

      // 1. natychmiast: pinezka i skok do punktu, ktory mapa juz ma
      const lokalna = kolekcja.current?.features.find(
        (f) => Number(f.id) === wybrana,
      );
      if (lokalna?.geometry.type === "Point") {
        const [lon, lat] = lokalna.geometry.coordinates as [number, number];
        postawPinezke(lon, lat);
        m.flyTo({
          center: [lon, lat],
          zoom: Math.max(m.getZoom(), 15),
          duration: 500,
        });
      }

      // 2. po odpowiedzi: obrys dzialki i kadr na jej granicach
      const numer = ++zadanie.current;
      const znane = zapamietane.current.get(wybrana);
      if (znane) {
        pokazObrys(znane);
        return;
      }
      pobierzObrys(wybrana)
        .then((dane) => {
          zapamietane.current.set(wybrana, dane);
          // Uzytkownik zdazyl kliknac inna oferte: ta odpowiedz jest nieaktualna
          if (zadanie.current !== numer) return;
          pokazObrys(dane);
        })
        .catch(() => {
          // Pinezka zostaje: bez API nadal wiemy, gdzie oferta jest, bo punkt
          // przyszedl z lista. Znika tylko obrys i podpis.
          if (zadanie.current !== numer) return;
          (m.getSource("wybor") as GeoJSONSource | undefined)?.setData(PUSTA);
          setOpisObrysu(null);
        });
    };

    if (gotowa.current) zastosuj();
    else m.once("idle", zastosuj);
  }, [wybrana, pokazObrys, postawPinezke, zdejmijPinezke]);

  const pewny = Boolean(
    opisObrysu?.obrys && opisObrysu.pewnosc && PEWNE.has(opisObrysu.pewnosc),
  );

  return (
    <div className="szklo mapa-podklad relative h-full w-full overflow-hidden">
      <div ref={kontener} className="h-full w-full" />
      {opisObrysu && (
        <div className="pointer-events-none absolute right-3 top-3 max-w-[16rem] rounded-lg border border-slate-200 bg-white/90 px-3 py-1.5 text-xs text-slate-600 shadow-[0_10px_24px_-14px_rgba(30,68,112,0.6)] backdrop-blur-md dark:border-white/10 dark:bg-slate-900/60 dark:text-slate-300">
          {pewny ? (
            <>
              <span className="font-medium text-slate-900 dark:text-slate-100">
                działka {opisObrysu.uldk_id?.split(".").pop()}
              </span>
              {opisObrysu.powierzchnia_ewid_m2 && (
                <>
                  {" · "}
                  {opisObrysu.powierzchnia_ewid_m2.toLocaleString("pl-PL")} m²
                </>
              )}
              {opisObrysu.pewnosc === "medium" && (
                <div className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                  powierzchnia się zgadza, ale punkt z ogłoszenia leży obok
                </div>
              )}
            </>
          ) : (
            <>
              <span className="font-medium text-slate-900 dark:text-slate-100">
                pinezka, bez obrysu
              </span>
              <div className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                {opisObrysu.pewnosc === "low"
                  ? "działki nie da się wskazać pewnie: powierzchnia z ewidencji nie zgadza się z ogłoszeniem"
                  : "ogłoszenie nie dało się powiązać z działką ewidencyjną"}
              </div>
            </>
          )}
        </div>
      )}
      <div className="pointer-events-none absolute bottom-3 left-3 flex gap-3 rounded-lg border border-slate-200 bg-white/90 px-3 py-1.5 text-xs text-slate-600 shadow-[0_10px_24px_-14px_rgba(30,68,112,0.6)] backdrop-blur-md dark:border-white/10 dark:bg-slate-900/60 dark:text-slate-300">
        <Legenda kolor="#0f8f64" opis="score 70+" />
        <Legenda kolor="#0f5f89" opis="50-69" />
        <Legenda kolor="#c98f2a" opis="poniżej 50" />
        <Legenda kolor="#9a938a" opis="brak danych" />
      </div>
    </div>
  );
}

function Legenda({ kolor, opis }: { kolor: string; opis: string }) {
  return (
    <span className="flex items-center gap-1">
      <span
        className="inline-block h-2.5 w-2.5 rounded-full"
        style={{ backgroundColor: kolor }}
      />
      {opis}
    </span>
  );
}
