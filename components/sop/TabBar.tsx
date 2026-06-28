"use client";
import Link from "next/link";

interface TabBarProps {
  activeTab: "suggestions" | "digest";
  date: string;
}

export function TabBar({ activeTab, date }: TabBarProps) {
  const tabs = [
    { key: "suggestions" as const, label: "Factor Suggestions" },
    { key: "digest" as const, label: "Daily Digest" },
  ];

  return (
    <div className="flex border-b border-[--hairline] mb-8">
      {tabs.map((t) => {
        const isActive = activeTab === t.key;
        return (
          <Link
            key={t.key}
            href={`/sop/${date}${t.key === "digest" ? "?tab=digest" : ""}`}
            className={
              "px-5 py-3 text-[14px] font-medium border-b-2 transition -mb-[1px] " +
              (isActive
                ? "border-[--primary] text-[--ink]"
                : "border-transparent text-[--muted] hover:text-[--body]")
            }
          >
            {t.label}
          </Link>
        );
      })}
    </div>
  );
}
