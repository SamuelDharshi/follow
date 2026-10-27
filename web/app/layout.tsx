import type { Metadata } from "next";
import { Inter_Tight, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import Shell from "@/components/Shell";

// Display face: Inter Tight (variable, so weight 450 works). Labels: JetBrains Mono.
const sans = Inter_Tight({ subsets: ["latin"], variable: "--font-sans" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Follow - Strike market quality",
  description:
    "How deep is Strike's book? A liquidity scorecard built from Strike's public L3 feed, benchmarked against Binance and Hyperliquid.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <a href="#content" className="skip">Skip to content</a>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
