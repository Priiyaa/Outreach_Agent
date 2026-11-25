import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import FetchControl from "@/components/FetchControl";
import NavLink from "@/components/NavLink";
import Providers from "@/components/Providers";
import UnlockControl from "@/components/UnlockControl";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Job search",
  description: "Early-career tech roles for international students, filtered for you.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full">
        <Providers>
          <header className="border-b border-zinc-200 dark:border-zinc-800">
            <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-6 px-4 py-3">
              <h1 className="text-lg font-semibold">Job search</h1>
              <nav className="flex gap-4" aria-label="Main">
                <NavLink href="/">Jobs</NavLink>
                <NavLink href="/applied">Applied companies</NavLink>
                <NavLink href="/profile">Profile</NavLink>
              </nav>
              <span className="flex-1" />
              <UnlockControl />
              <FetchControl />
            </div>
          </header>
          <main className="mx-auto max-w-[1500px] px-4 py-6">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
