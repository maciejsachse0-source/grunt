import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { KursorGuzikow } from "@/components/KursorGuzikow";

// Podzbior latin-ext, bo bez niego polskie znaki diakrytyczne leca na fallback
// i naglowki rozjezdzaja sie w polowie wyrazu.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin", "latin-ext"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin", "latin-ext"],
});

export const metadata: Metadata = {
  title: "GRUNT — Land Investment Scoring",
  description:
    "Land listings aggregated from Polish real estate portals and enriched with public registries — cadastral parcels, local zoning plans, flood risk zones, utility access, and market valuations derived from real transaction prices (RCN) — to score investment potential.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // suppressHydrationWarning tylko na <html> i <body>: rozszerzenia przegladarki
    // (menedzery hasel, wtyczki zakupowe, tlumacze) dopisuja do tych dwoch znacznikow
    // wlasne atrybuty, zanim React sie podepnie. Serwer ich nie zna, wiec React
    // zglasza niezgodnosc hydracji, ktora nie jest bledem aplikacji. Tlumienie
    // dziala jeden poziom w glab, wiec prawdziwe roznice w tresci strony nadal
    // beda widoczne.
    <html
      lang="pl"
      // Bez klasy dark: interfejs ma jeden motyw, jasny, niezalezny od ustawienia
      // systemu. Wariant dark: jest w globals.css przypiety do tej klasy, wiec
      // pary "kolor / dark:kolor" rozstrzygaja sie na wersje jasna.
      className={`${inter.variable} ${jetbrainsMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body
        className="min-h-full flex flex-col font-sans text-slate-900"
        suppressHydrationWarning
      >
        {children}
        {/* Nic nie rysuje. Podaje tylko arkuszowi punkt, w ktorym kursor
            dotknal guzika, zeby wypelnienie wychodzilo wlasnie stamtad. */}
        <KursorGuzikow />
      </body>
    </html>
  );
}
