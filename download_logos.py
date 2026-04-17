#!/usr/bin/env python3
"""
download_logos.py - Downloads team logos from ESPN's CDN and saves at 20x20.

Run to populate or refresh logos:
    python3 download_logos.py           # skip already-correct files
    python3 download_logos.py --force   # re-download everything

Logos are saved to:
    logos/nfl/<ABBR>.png
    logos/nba/<ABBR>.png
"""

import os
import sys
import requests
from PIL import Image
from io import BytesIO

# ESPN CDN team logo URL template
ESPN_LOGO_URL = "https://a.espncdn.com/i/teamlogos/{sport}/500/{abbr}.png"

NFL_TEAMS = [
    "ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN",
    "DET","GB","HOU","IND","JAX","KC","LAC","LAR","LV","MIA",
    "MIN","NE","NO","NYG","NYJ","PHI","PIT","SEA","SF","TB",
    "TEN","WAS"
]

NBA_TEAMS = [
    "ATL","BKN","BOS","CHA","CHI","CLE","DAL","DEN","DET","GS",
    "HOU","IND","LAC","LAL","MEM","MIA","MIL","MIN","NO","NY",
    "OKC","ORL","PHI","PHX","POR","SAC","SA","TOR","UTAH","WSH"
]

# ESPN CDN uses different abbreviations for some teams.
# Keys are the ESPN API abbreviation (used as the logo filename).
# Values are the CDN path component (lowercased before use).
NBA_CDN_REMAP = {
    "GS":  "gsw",   # Golden State Warriors
    "NY":  "nyk",   # New York Knicks
    "SA":  "sas",   # San Antonio Spurs
    "WSH": "was",   # Washington Wizards
}

LOGO_SIZE = (18, 18)
OUTPUT_DIRS = {
    "nfl": "logos/nfl",
    "nba": "logos/nba",
}

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (compatible; ScoreBug/1.0)"

def _lum(p):
    return int(0.21 * p[0] + 0.72 * p[1] + 0.07 * p[2])

def _clean_logo(img, lum_threshold=35, star_rows=7):
    """
    Drop dim edge/fringe pixels (lum < lum_threshold) across the whole image,
    then scan the top `star_rows` rows for connected pixel clusters and
    force-restore the brightest pixel of each cluster so at least one LED
    lights up per star.
    """
    pixels = list(img.getdata())
    w, h = img.size
    out = [p if _lum(p) >= lum_threshold else (0, 0, 0) for p in pixels]

    visited = [[False] * w for _ in range(star_rows)]

    def flood(sy, sx):
        stack, cluster = [(sy, sx)], []
        while stack:
            y, x = stack.pop()
            if y < 0 or y >= star_rows or x < 0 or x >= w:
                continue
            if visited[y][x] or _lum(pixels[y * w + x]) <= 4:
                continue
            visited[y][x] = True
            cluster.append((y, x))
            for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                stack.append((y + dy, x + dx))
        return cluster

    for sy in range(star_rows):
        for sx in range(w):
            if not visited[sy][sx] and _lum(pixels[sy * w + sx]) > 4:
                cluster = flood(sy, sx)
                by, bx = max(cluster, key=lambda pos: _lum(pixels[pos[0] * w + pos[1]]))
                out[by * w + bx] = pixels[by * w + bx]

    result = Image.new("RGB", img.size, (0, 0, 0))
    result.putdata(out)
    return result

# Logos that use _clean_logo() post-processing after direct 500->18 resize.
# Value is (lum_threshold, star_rows).
CLEAN_LOGOS = {
    ("nba", "PHI"): (10, 7),
}

def download_logo(sport: str, abbr: str, output_dir: str, force: bool = False,
                  cdn_remap: dict = None):
    cdn_abbr = (cdn_remap or {}).get(abbr, abbr).lower()
    url = ESPN_LOGO_URL.format(sport=sport, abbr=cdn_abbr)
    path = os.path.join(output_dir, f"{abbr}.png")
    if not force and os.path.exists(path):
        try:
            existing = Image.open(path)
            if existing.size == LOGO_SIZE:
                print(f"  [skip] {abbr}")
                return
            print(f"  [redo] {abbr} wrong size {existing.size}")
        except Exception:
            pass
    try:
        resp = session.get(url, timeout=10)
        resp.raise_for_status()
        # Resize FIRST while the image is still RGBA (transparent background),
        # THEN composite over black.  Doing it the other way (composite-then-resize)
        # causes LANCZOS to blend the logo colours with the black border pixels,
        # making the entire logo appear darker and washed-out at small sizes.
        img = Image.open(BytesIO(resp.content)).convert("RGBA")
        clean_params = CLEAN_LOGOS.get((sport, abbr))
        if clean_params:
            # Direct 500->final resize, then luminance threshold + star preservation.
            small = img.resize(LOGO_SIZE, Image.LANCZOS)
            bg = Image.new("RGB", LOGO_SIZE, (0, 0, 0))
            bg.paste(small.convert("RGB"), mask=small.split()[3])
            bg = _clean_logo(bg, *clean_params)
        else:
            # Two-step resize to preserve fine details (star rings, thin strokes).
            # Step 1: resize to 80×80 and harden semi-transparent detail pixels so
            # they survive the second downsample without being averaged into nothing.
            MID = 80
            mid = img.resize((MID, MID), Image.LANCZOS)
            mr, mg, mb, ma = mid.split()
            ma_d = list(ma.getdata())
            mr_d, mg_d, mb_d = list(mr.getdata()), list(mg.getdata()), list(mb.getdata())
            lum_m = [int(0.21*rv + 0.72*gv + 0.07*bv)
                     for rv, gv, bv in zip(mr_d, mg_d, mb_d)]
            ha = [255 if (av >= 32 or (av >= 12 and lv >= 50)) else 0
                  for av, lv in zip(ma_d, lum_m)]
            nma = ma.copy()
            nma.putdata(ha)
            mid = Image.merge("RGBA", (mr, mg, mb, nma))
            # Step 2: resize hardened intermediate to final size
            img = mid.resize(LOGO_SIZE, Image.LANCZOS)
            # Final luminance-aware threshold: keep bright detail at low alpha,
            # drop dark fringe pixels that are invisible on a black LED matrix.
            r, g, b, a = img.split()
            r_d, g_d, b_d, a_d = list(r.getdata()), list(g.getdata()), \
                                  list(b.getdata()), list(a.getdata())
            lum = [int(0.21*rv + 0.72*gv + 0.07*bv)
                   for rv, gv, bv in zip(r_d, g_d, b_d)]
            new_a = [255 if (av >= 128 or (av >= 24 and lv >= 80)) else 0
                     for av, lv in zip(a_d, lum)]
            a = a.copy()
            a.putdata(new_a)
            img = Image.merge("RGBA", (r, g, b, a))
            bg = Image.new("RGB", LOGO_SIZE, (0, 0, 0))
            bg.paste(img, mask=a)
        bg.save(path)
        print(f"  [ok]   {abbr} -> {path}")
    except Exception as e:
        print(f"  [err]  {abbr}: {e}")

def main():
    force = '--force' in sys.argv
    if force:
        print("Force mode — re-downloading all logos")
    remap = {"nba": NBA_CDN_REMAP, "nfl": {}}
    for sport, teams in [("nfl", NFL_TEAMS), ("nba", NBA_TEAMS)]:
        out = OUTPUT_DIRS[sport]
        os.makedirs(out, exist_ok=True)
        print(f"\nDownloading {sport.upper()} logos -> {out}/")
        for abbr in teams:
            download_logo(sport, abbr, out, force=force, cdn_remap=remap[sport])
    print("\nDone. Logos ready.")

if __name__ == "__main__":
    main()
