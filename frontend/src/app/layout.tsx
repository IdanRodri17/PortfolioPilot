import type { Metadata } from "next";
import { Spectral, Hanken_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

// Editorial theme: Spectral (display serif), Hanken Grotesk (UI/body),
// JetBrains Mono (tickers, figures, labels). CSS-variable pattern preserved so
// globals.css can map them to --font-serif / --font-sans / --font-mono.
const spectral = Spectral({
  variable: "--font-spectral",
  weight: ["300", "400", "500", "600"],
  subsets: ["latin"],
});

const hanken = Hanken_Grotesk({
  variable: "--font-hanken",
  subsets: ["latin"],
});

const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "PortfolioPilot",
  description: "AI wealth manager",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${spectral.variable} ${hanken.variable} ${jetbrains.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
