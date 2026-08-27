"""Download a small set of public-domain portraits for a sanity check.

This is NOT calibration data. It exists to answer one narrower question that
was still open: does the YuNet + SFace pipeline actually tell people apart, or
have we wired something up backwards? For that, any set of real faces with
several photographs each will do.

It cannot answer the question that matters for deployment. These are studio and
press photographs of public figures; learners will be sitting at whatever
webcam they own, in whatever light their room has. A threshold measured here
would be measured on the wrong distribution, and using it would be worse than
using the model author's default, because it would look like it had been
validated.

Sources are Wikimedia Commons files whose licence is public domain — official
works of the US federal government are not copyrighted, so there is no research
-only clause to argue about later. Each downloaded file's licence is recorded
in CREDITS.md beside it.

    python fetch-reference-faces.py --out tests/faces-public
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "face-recognition-calibration-sanity-check/1.0"

# Chosen because each has several official photographs on Commons and those
# photographs are US federal works, i.e. public domain. Names are only labels
# here; nothing about these people is stored beyond the files themselves.
PEOPLE = {
    "obama": [
        "President Barack Obama.jpg",
        "Official portrait of Barack Obama.jpg",
        "Barack Obama addresses joint session of Congress 2009-02-24.jpg",
    ],
    "biden": [
        "Joe Biden presidential portrait.jpg",
        "Joe Biden official portrait 2013 cropped.jpg",
        "Vice President Joe Biden official portrait 2013.jpg",
    ],
    "harris": [
        "Kamala Harris Vice Presidential Portrait.jpg",
        "Kamala Harris official photo (cropped2).jpg",
        "Senator Harris official senate portrait.jpg",
    ],
    "yellen": [
        "Janet Yellen official Federal Reserve portrait.jpg",
        "Janet Yellen official portrait as Treasury Secretary.jpg",
        "Janet Yellen, Chair of the Board of Governors of the Federal Reserve System.jpg",
    ],
    "fauci": [
        "Anthony S. Fauci, M.D., NIAID Director (26759498706).jpg",
        "Anthony Fauci NIAID.jpg",
        "Dr. Anthony Fauci - NIH.jpg",
    ],
}


# Commons rate-limits anonymous callers hard. One request a second with backoff
# on 429 keeps a script that downloads fifteen pictures from looking like abuse.
_MIN_INTERVAL = 1.2
_last_call = 0.0


def _throttled_open(url: str, timeout: int):
    global _last_call

    for attempt in range(5):
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()

        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 4:
                raise
            backoff = 2 ** attempt
            print(f"  rate limited, waiting {backoff}s")
            time.sleep(backoff)

    raise RuntimeError("unreachable")


def api_get(params: dict) -> dict:
    params = {**params, "format": "json"}
    url = f"{API}?{urllib.parse.urlencode(params)}"
    with _throttled_open(url, timeout=60) as response:
        return json.load(response)


def images_info(filenames: list[str]) -> dict[str, dict]:
    """URL and licence for several files in one request.

    MediaWiki takes up to fifty titles per query. Asking once per file is what
    tripped Commons' rate limiter; asking once per person does not.
    """
    titles = "|".join(f"File:{name}" for name in filenames)
    data = api_get({
        "action": "query",
        "titles": titles,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": "900",
    })

    query = data.get("query", {})
    # Commons resolves redirects and normalises titles, so the key coming back
    # is not always the string that went in.
    canonical: dict[str, str] = {}
    for entry in query.get("normalized", []) + query.get("redirects", []):
        canonical[entry["to"]] = entry["from"]

    found: dict[str, dict] = {}
    for page in query.get("pages", {}).values():
        if "imageinfo" not in page:
            continue
        info = page["imageinfo"][0]
        meta = info.get("extmetadata", {})
        title = page.get("title", "")
        requested = canonical.get(title, title).removeprefix("File:")
        found[requested] = {
            "url": info.get("thumburl") or info.get("url"),
            "licence": meta.get("LicenseShortName", {}).get("value", "unknown"),
            "page": info.get("descriptionurl", ""),
        }
    return found


def search_alternatives(person: str, limit: int) -> list[str]:
    """Fallback when a hard-coded filename has been renamed on Commons."""
    data = api_get({
        "action": "query",
        "list": "search",
        "srsearch": f"official portrait {person}",
        "srnamespace": "6",
        "srlimit": str(limit),
    })
    return [
        hit["title"].removeprefix("File:")
        for hit in data.get("query", {}).get("search", [])
        if hit["title"].lower().endswith((".jpg", ".jpeg", ".png"))
    ]


def download(url: str, target: Path) -> int:
    with _throttled_open(url, timeout=120) as response:
        payload = response.read()
    target.write_bytes(payload)
    return len(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(Path(__file__).parent / "tests" / "faces-public"))
    parser.add_argument("--per-person", type=int, default=3)
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    credits: list[str] = [
        "# Where these photographs came from",
        "",
        "Downloaded by `fetch-reference-faces.py` for one purpose: checking that",
        "the face pipeline tells people apart. **These are not calibration data.**",
        "They are press and studio photographs of public figures; learners will be",
        "at a webcam in an ordinary room, and a threshold measured here would be",
        "measured on the wrong distribution.",
        "",
        "| ไฟล์ | ที่มา | ไลเซนส์ |",
        "|---|---|---|",
    ]

    total = 0
    for person, filenames in PEOPLE.items():
        person_dir = out / person
        person_dir.mkdir(exist_ok=True)

        got = 0
        available = images_info(filenames)

        for index, filename in enumerate(filenames, start=1):
            if got >= args.per_person:
                break
            info = available.get(filename)
            if not info or not info["url"]:
                print(f"  skip {filename}: not on Commons under that name")
                continue

            # Public domain only. A research-only clause discovered later is
            # exactly the kind of problem this project already had once.
            licence = info["licence"]
            if "public domain" not in licence.lower() and not licence.lower().startswith("pd"):
                print(f"  skip {filename}: licence is {licence!r}")
                continue

            target = person_dir / f"{index}{Path(filename).suffix.lower()}"
            try:
                size = download(info["url"], target)
            except Exception as error:  # noqa: BLE001
                print(f"  skip {filename}: {error}")
                continue

            got += 1
            total += 1
            print(f"  ok   {person}/{target.name}  {size // 1024}KB  {licence}")
            credits.append(f"| `{person}/{target.name}` | [{filename}]({info['page']}) | {licence} |")


        if got < 2:
            print(f"  WARNING: only {got} usable photo(s) for {person}; "
                  "searching Commons for alternatives")
            alternatives = search_alternatives(person, 8)
            found = images_info(alternatives) if alternatives else {}
            for filename in alternatives:
                if got >= args.per_person:
                    break
                info = found.get(filename)
                if not info or not info["url"]:
                    continue
                if "public domain" not in info["licence"].lower():
                    continue
                target = person_dir / f"alt{got + 1}{Path(filename).suffix.lower()}"
                try:
                    size = download(info["url"], target)
                except Exception:  # noqa: BLE001
                    continue
                got += 1
                total += 1
                print(f"  ok   {person}/{target.name}  {size // 1024}KB  {info['licence']}")
                credits.append(
                    f"| `{person}/{target.name}` | [{filename}]({info['page']}) | {info['licence']} |")


    (out / "CREDITS.md").write_text("\n".join(credits) + "\n", encoding="utf-8")
    print(f"\ndownloaded {total} photographs to {out}")
    print(f"licences recorded in {out / 'CREDITS.md'}")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
