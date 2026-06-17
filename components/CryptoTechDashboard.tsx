"use client";

import Nav from "./Nav";

export default function CryptoTechDashboard() {
  return (
    <div className="flex flex-col bg-[#0f1117] text-white" style={{ height: "100dvh" }}>
      <header className="border-b border-[#2d3144] px-6 py-4 shrink-0">
        <div className="max-w-7xl mx-auto flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Best15 Strategy</h1>
            <p className="text-gray-400 text-sm mt-0.5">Crypto Top 15 · BTC 50% Cap</p>
          </div>
          <Nav />
        </div>
      </header>
      <iframe
        src="https://crypto-tech-dashboard-2nd-try-v2-0.vercel.app/#token=bitcoin"
        className="w-full flex-1 border-0"
        allow="fullscreen"
        title="IOSG Crypto Tech Dashboard"
      />
    </div>
  );
}
