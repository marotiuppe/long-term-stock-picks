"""The held-out track record as a plain-text report, so anyone can read exactly what the About and Home pages summarise.

The daily scan builds this report itself (server.run_scan) and the app serves it at /api/track-record, so nothing has to be run by hand.
Running this file is optional and only repeats the report offline from the newest cache/rows-*.pkl, from the app folder:
    python -m modules.about.backtest
"""
import glob
import os
import pickle


def format_report(track, n_stocks, n_pool, n_train, n_held, cutoff, purge_days, source):
    """Pure text builder. track: server.track_record(pool). source: where the rows came from (shown on the first line)."""
    out = [f"{source}: {n_stocks} stocks, {n_pool} stock-dates",
           f"forecast pool {n_train} rows before {cutoff}; held-out {n_held} rows, purge {purge_days} days after the cutoff",
           "survivorship caveat: only stocks still listed today are included, which flatters every number."]
    for k, t in track.items():
        out += ["", f"[{k}] held-out {t['start']} to {t['end']}",
                f"  buy-grade rows {t['n']} (effective {t['effective_n']:.0f}), all-stock rows {t['all_n']} (effective {t['all_effective_n']:.0f})",
                f"  hit rate buy {t['hit']*100:.1f}% vs all {t['all_hit']*100:.1f}%",
                f"  edge {t['edge']*100:+.1f} pts, 95% interval {t['edge_lo']*100:+.1f} to {t['edge_hi']*100:+.1f}"
                + ("  (includes 0: not distinguishable from zero)" if t["edge_lo"] <= 0 <= t["edge_hi"] else ""),
                f"  median buy {t['median']*100:+.1f}% vs all {t['all_median']*100:+.1f}%, worst 10% of picks {t['worst10']*100:+.1f}%"]
    return "\n".join(out) + "\n"


def main():
    import server   # only the command line needs the scan code; the server itself imports this module
    files = sorted(glob.glob(os.path.join(server.CACHE_DIR, "rows-*.pkl")))
    if not files:
        raise SystemExit("no cache/rows-*.pkl found; run the app once to download prices")
    with open(files[-1], "rb") as f:
        res = pickle.load(f)
    nrows = res.pop("^NSEI", None)
    data = {s: r for s, r in res.items() if r and not server.passes_quality(r)}
    pool, _ = server.build_pool(data, nrows)
    train, held, cutoff = server.split_pool(pool)
    print(format_report(server.track_record(pool), len(data), len(pool), len(train), len(held), cutoff, server.PURGE_DAYS,
                        "cache " + os.path.basename(files[-1])), end="")


if __name__ == "__main__":
    main()
