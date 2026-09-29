"""Report settimanale in italiano (Markdown), pronto per una Issue GitHub = email automatica."""
from __future__ import annotations

from datetime import date


def _fmt_users(n: int | None) -> str:
    return f"{n:,}".replace(",", ".") if n is not None else "?"


def build_report(top: list[dict], stats: dict, today: date | None = None) -> str:
    today = today or date.today()
    lines = [
        f"# Estensioni orfane – report del {today.strftime('%d/%m/%Y')}",
        "",
        f"Database: **{_fmt_users(stats.get('total'))}** estensioni note, "
        f"**{_fmt_users(stats.get('fetched'))}** lette, "
        f"**{_fmt_users(stats.get('removed'))}** rimosse dallo store.",
        "",
    ]
    if not top:
        lines += ["Nessuna nuova occasione questa settimana: la scansione e' ancora in corso "
                  "oppure nessuna supera i filtri."]
        return "\n".join(lines)

    lines += [
        "## Le migliori occasioni",
        "",
        "| # | Estensione | Utenti | Voto | Fermo da | Stato | Punteggio |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(top, 1):
        name = (r.get("name") or r["ext_id"]).replace("|", "/")
        rating = f"{r['rating']:.1f} ({r.get('rating_count') or 0})" if r.get("rating") else "–"
        stale = f"{r['stale_days'] // 30} mesi" if r.get("stale_days") is not None else "?"
        state = "RIMOSSA" if r.get("removed_at") else "nello store"
        lines.append(
            f"| {i} | [{name}]({r['url']}) | {_fmt_users(r.get('users'))} | {rating} | "
            f"{stale} | {state} | {r['score']} |"
        )
    lines += [
        "",
        "**Cosa fare:** scegli 1–2 candidati e rispondi qui sotto. Prima di costruire controlliamo "
        "che non esista gia' un sostituto valido e che l'idea rispetti le regole dello store.",
    ]
    return "\n".join(lines)
