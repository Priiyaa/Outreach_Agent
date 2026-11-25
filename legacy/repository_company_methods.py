"""DB methods for company sizing, removed from app/db/repository.py (class DB) on 2026-11-16."""

    def company_sizes(self) -> dict[str, RowMapping]:
        return {r["key"]: r for r in self.query("SELECT * FROM companies")}

    def companies_with_jobs(self) -> list[RowMapping]:
        """Companies that have open jobs, with how many of them come from the company's own board."""
        return self.query(
            "SELECT company_key AS key, MIN(company) AS name, "
            f"SUM(CASE WHEN source IN ({_DIRECT}) THEN 1 ELSE 0 END) AS openings "
            "FROM jobs WHERE company_key IS NOT NULL AND closed_at IS NULL GROUP BY company_key"
        )

    def descriptions_for(self, company_key: str, limit: int = 25) -> list[str]:
        rows = self.query(
            "SELECT description FROM jobs WHERE company_key = :key AND description != '' "
            f"AND source IN ({_DIRECT}) LIMIT :limit",
            key=company_key, limit=limit,
        )
        return [r["description"] for r in rows]

    def set_company_size(self, key: str, name: str, size: str, source: str,
                         employees: int | None = None, ts: str | None = None) -> None:
        self.execute(
            "INSERT INTO companies (key, name, size, employees, size_source, updated_at) "
            "VALUES (:key, :name, :size, :employees, :source, :ts) "
            "ON CONFLICT(key) DO UPDATE SET name = excluded.name, size = excluded.size, "
            "employees = excluded.employees, size_source = excluded.size_source, "
            "updated_at = excluded.updated_at",
            {"key": key, "name": name, "size": size, "employees": employees, "source": source, "ts": ts or _now()},
        )

    # ---- edits made in the app ------------------------------------------------------------------

