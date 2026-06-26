"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/cycle-signals",  label: "Cycle Signal",   experimental: false },
  { href: "/crash-cluster",  label: "Crash Cluster",  experimental: true },
  { href: "/private-fund",   label: "Private Fund",   experimental: false },
  { href: "/valuation",      label: "Valuations",     experimental: false },
  { href: "/crypto-tech",    label: "Tech Dashboard", experimental: false },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <nav className="flex gap-1 flex-wrap">
      {LINKS.map(({ href, label, experimental }) => {
        const active = pathname === href;
        return (
          <Link
            key={href}
            href={href}
            className="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors flex items-center gap-1.5"
            style={{
              background: active ? "#3b82f622" : "transparent",
              color: active ? "#60a5fa" : "#6b7280",
              border: `1px solid ${active ? "#3b82f6" : "#3d4166"}`,
            }}
          >
            {label}
            {experimental && (
              <span className="text-[10px] font-bold px-1 py-0 rounded bg-amber-500/20 text-amber-400 leading-4">
                EXP
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}
