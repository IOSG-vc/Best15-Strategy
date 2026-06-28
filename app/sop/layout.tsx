import { Cormorant_Garamond, JetBrains_Mono } from "next/font/google";

const displaySerif = Cormorant_Garamond({
  variable: "--font-sop-display",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

const mono = JetBrains_Mono({
  variable: "--font-sop-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
});

export default function SopLayout({ children }: { children: React.ReactNode }) {
  return (
    <div
      className={`sop-page min-h-screen flex flex-col ${displaySerif.variable} ${mono.variable}`}
      style={{ fontFamily: "var(--font-sans, Inter, sans-serif)" }}
    >
      {children}
    </div>
  );
}
