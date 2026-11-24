import type { Metadata } from "next";
import { Manrope, IBM_Plex_Mono } from "next/font/google";

import "katex/dist/katex.min.css";
import "./globals.css";
import "./views.css";

const manrope = Manrope({ subsets: ["latin"], variable: "--font-manrope", display: "swap" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-ibm-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Vektor | Operations assistant",
  description: "AI operations assistant for database and infrastructure workflows.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${manrope.variable} ${mono.variable}`} data-theme="dark" suppressHydrationWarning>
      <head>
        {/* Runs before paint so a saved light choice does not flash dark on load. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=JSON.parse(localStorage.getItem("vektor:theme")||'null');document.documentElement.dataset.theme=t==="light"?"light":"dark"}catch(e){document.documentElement.dataset.theme="dark"}`,
          }}
        />
      </head>
      <body className="page-body" suppressHydrationWarning>{children}</body>
    </html>
  );
}
