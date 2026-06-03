"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/cycle-signals", label: "Cycle Signal" },
  { href: "/private-fund", label: "Private Fund" },
  { href: "/valuation",    label: "Valuations" },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <nav className="flex gap-1">
      {LINKS.map(({ href, label }) => {
        const active = pathname === href;
        return (
          <Link
            key={href}
            href={href}
            className="px-4 py-1.5 rounded-lg text-sm font-medium transition-colors"
            style={{
              background: active ? "#3b82f622" : "transparent",
              color: active ? "#60a5fa" : "#6b7280",
              border: `1px solid ${active ? "#3b82f6" : "#3d4166"}`,
            }}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
