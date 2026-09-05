"use client";

import { useState } from "react";

import {
  Activity,
  ArrowLeft,
  BarChart2,
  Command,
  Database,
  Layers,
  Sparkles,
  Users,
} from "lucide-react";

import type {
  NotchItemData,
  NotchPosition,
} from "@/components/ui/adaptive-notch-navigation-bar";

import { NotchNav } from "@/components/ui/adaptive-notch-navigation-bar";

const NAV_ITEMS: NotchItemData[] = [
  { id: "dashboard", label: "Dashboard", icon: BarChart2 },
  { id: "profiles", label: "Profiles", icon: Users },
  { id: "funnels", label: "Funnels", icon: Layers },
  { id: "performance", label: "Performance", icon: Activity },
  { id: "realtime", label: "Realtime", icon: Sparkles, badge: "Live" },
];

const SoraLogo = (
  <div className="flex items-center gap-1.5 sm:gap-2 h-8.5">
    <div className="flex size-7 items-center justify-center rounded-lg bg-zinc-800 dark:bg-zinc-300">
      <Command className="size-4 text-zinc-50 dark:text-zinc-950" />
    </div>
    <span className="hidden sm:inline text-xs sm:text-sm font-bold tracking-tight">
      SARA
    </span>
  </div>
);

export default function NotchNavSaraDemo() {
  const [activeId, setActiveId] = useState<string>("dashboard");

  const [position, setPosition] = useState<NotchPosition>("top");

  const handleResetDb = () => {
    console.log("Reset DB triggered");
  };

  const handleActiveChange = (id: string) => {
    setActiveId(id);
  };

  return (
    <NotchNav
      items={NAV_ITEMS}
      activeId={activeId}
      position={position}
      logo={SoraLogo}
      showLogo={true}
      showRightContent={false}
      onActiveChange={handleActiveChange}
      onResetDb={handleResetDb}
    >
      <div className="flex w-full max-w-xs flex-col items-center gap-4 rounded-2xl border border-border bg-card p-5 text-center shadow-xs">
        <div className="flex flex-col items-center">
          <span className="text-xs font-medium text-muted-foreground">
            Active Tab
          </span>

          <p className="text-lg font-bold text-foreground capitalize">
            {activeId}
          </p>
        </div>

        <div className="flex w-full flex-col gap-2">
          <button
            type="button"
            onClick={() =>
              setPosition((prev) => (prev === "top" ? "bottom" : "top"))
            }
            className="flex w-full cursor-pointer items-center justify-between rounded-xl border border-border bg-background px-3.5 py-2 text-xs font-semibold text-foreground shadow-xs transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring outline-none"
          >
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <ArrowLeft className="size-3.5" />
              Position
            </span>

            <span className="font-bold text-foreground capitalize">
              {position}
            </span>
          </button>

          <button
            type="button"
            onClick={handleResetDb}
            className="flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-xl border border-border bg-background py-2 text-xs font-semibold text-foreground shadow-xs transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring outline-none"
          >
            <Database className="size-3.5" />
            Reset Database
          </button>
        </div>
      </div>
    </NotchNav>
  );
}
