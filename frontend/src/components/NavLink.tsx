"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  const active = usePathname() === href;
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`border-b-2 px-1 pb-1 text-sm ${active ? "border-blue-600 font-semibold" : "border-transparent text-zinc-500 hover:text-foreground"}`}
    >
      {children}
    </Link>
  );
}
