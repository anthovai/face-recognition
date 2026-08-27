"""Work out the face-matching thresholds from real photographs.

Nothing in this system should trust a similarity score until this has been run.
The shipped default (0.363) is SFace's author's reference value measured on
their benchmark, not on the cameras, lighting and people this deployment will
actually see. The earlier prototype carried a threshold of 0.42 that was never
checked against a single real photograph, which is the mistake this exists to
prevent repeating.

Photographs go in ``face-service/tests/faces/``, either as::

    faces/somchai_1.jpg   faces/somchai_2.jpg   faces/nid_1.jpg

or one directory per person, which is usually easier to organise::

    faces/somchai/1.jpg   faces/somchai/enrolment.png   faces/nid/1.jpg

Then, from the project root::

    sh calibrate.sh

It runs inside the face-service container so the models and the OpenCV build
are exactly the ones production uses — calibrating against a different build
than you deploy is worse than not calibrating.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config, face_engine, liveness  # noqa: E402

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# The band below the match threshold where a score is treated as inconclusive:
# the learner is asked to reposition rather than accused of impersonation.
REVIEW_MARGIN = 0.06


def collect_photos(root: Path) -> dict[str, list[Path]]:
    """Group image files by person, accepting both layouts."""
    by_person: dict[str, list[Path]] = defaultdict(list)

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if path.parent == root:
            # faces/<person>_<n>.jpg — everything before the last underscore.
            person = path.stem.rsplit("_", 1)[0] if "_" in path.stem else path.stem
        else:
            # faces/<person>/<anything>.jpg
            person = path.parent.name
        by_person[person].append(path)

    return dict(by_person)


def embed_all(by_person: dict[str, list[Path]]) -> tuple[dict, list[dict]]:
    """Return embeddings per person and a per-photo diagnostic record."""
    embeddings: dict[str, list[np.ndarray]] = defaultdict(list)
    photos: list[dict] = []

    for person, paths in sorted(by_person.items()):
        for path in paths:
            record = {"person": person, "file": path.name, "usable": False}
            image = cv2.imread(str(path))
            if image is None:
                record["problem"] = "unreadable"
                photos.append(record)
                continue

            try:
                face = face_engine.extract_face(image)
            except face_engine.FaceEngineError as error:
                record["problem"] = error.code
                photos.append(record)
                continue

            live = liveness.check_liveness(image, face.bbox)
            width = face.bbox[2] - face.bbox[0]

            record.update({
                "usable": True,
                "det_score": round(face.det_score, 4),
                "face_width_px": int(width),
                "liveness": live["score"],
                "live": live["live"],
                "yaw": round(face.pose[1], 1),
            })
            photos.append(record)
            embeddings[person].append(face.embedding)

    return dict(embeddings), photos


def score_pairs(embeddings: dict[str, list[np.ndarray]]) -> tuple[list, list]:
    """Genuine scores (same person) and impostor scores (different people)."""
    genuine, impostor = [], []

    for person, vectors in embeddings.items():
        for a, b in itertools.combinations(vectors, 2):
            genuine.append((person, face_engine.cosine_similarity(a, b)))

    for (p1, v1), (p2, v2) in itertools.combinations(embeddings.items(), 2):
        for a in v1:
            for b in v2:
                impostor.append((f"{p1} vs {p2}", face_engine.cosine_similarity(a, b)))

    return genuine, impostor


def sweep(genuine: list[float], impostor: list[float]) -> list[dict]:
    """False-accept and false-reject rates across candidate thresholds."""
    rows = []
    for step in range(20, 121):
        threshold = step / 200.0  # 0.100 to 0.600 in steps of 0.005
        far = sum(1 for s in impostor if s >= threshold) / len(impostor) if impostor else 0.0
        frr = sum(1 for s in genuine if s < threshold) / len(genuine) if genuine else 0.0
        rows.append({"threshold": threshold, "far": far, "frr": frr})
    return rows


def recommend(genuine: list[float], impostor: list[float], rows: list[dict]) -> dict:
    """Pick a threshold, and be explicit about which rule produced it."""
    if not genuine or not impostor:
        return {"ok": False, "reason": "need at least two people with two photos each"}

    worst_genuine = min(genuine)
    best_impostor = max(impostor)

    if worst_genuine > best_impostor:
        # Cleanly separated: sit in the middle of the gap.
        threshold = (worst_genuine + best_impostor) / 2
        rule = "midpoint of a clean separation"
        separated = True
    else:
        # Overlapping: equal error rate is the least-bad single number, and
        # the report has to say the overlap exists.
        eer_row = min(rows, key=lambda r: abs(r["far"] - r["frr"]))
        threshold = eer_row["threshold"]
        rule = f"equal error rate (FAR {eer_row['far']:.1%}, FRR {eer_row['frr']:.1%})"
        separated = False

    return {
        "ok": True,
        "separated": separated,
        "match_threshold": round(threshold, 4),
        "review_min": round(max(0.0, threshold - REVIEW_MARGIN), 4),
        "rule": rule,
        "worst_genuine": round(worst_genuine, 4),
        "best_impostor": round(best_impostor, 4),
    }


def describe(scores: list[float]) -> dict:
    ordered = sorted(scores)
    return {
        "count": len(ordered),
        "min": round(ordered[0], 4),
        "median": round(ordered[len(ordered) // 2], 4),
        "max": round(ordered[-1], 4),
        "mean": round(float(np.mean(ordered)), 4),
    }


def write_report(path: Path, data: dict) -> None:
    lines: list[str] = []
    add = lines.append

    add("# ผลการปรับเทียบเกณฑ์การเทียบใบหน้า")
    add("")
    add(f"รันเมื่อ **{data['when']}** · โมเดล **{data['model_pack']}** · "
        f"service **{data['service_version']}**")
    add("")

    add("## ข้อมูลที่ใช้")
    add("")
    add("| | จำนวน |")
    add("|---|---|")
    add(f"| คน | **{data['people']}** |")
    add(f"| ภาพทั้งหมด | {data['photos_total']} |")
    add(f"| ภาพที่ใช้ได้ | **{data['photos_usable']}** |")
    add(f"| คู่ภาพคนเดียวกัน | {data['genuine']['count'] if data['genuine'] else 0} |")
    add(f"| คู่ภาพคนละคน | {data['impostor']['count'] if data['impostor'] else 0} |")
    add("")

    if data["unusable"]:
        add("### ภาพที่ใช้ไม่ได้")
        add("")
        add("| ไฟล์ | คน | เหตุผล |")
        add("|---|---|---|")
        for record in data["unusable"]:
            add(f"| `{record['file']}` | {record['person']} | `{record.get('problem', '?')}` |")
        add("")

    if data["genuine"] and data["impostor"]:
        add("## การกระจายของคะแนน")
        add("")
        add("| | ต่ำสุด | มัธยฐาน | สูงสุด | เฉลี่ย |")
        add("|---|---|---|---|---|")
        g, i = data["genuine"], data["impostor"]
        add(f"| คนเดียวกัน | **{g['min']}** | {g['median']} | {g['max']} | {g['mean']} |")
        add(f"| คนละคน | {i['min']} | {i['median']} | **{i['max']}** | {i['mean']} |")
        add("")
        add("ตัวเลขที่สำคัญคือสองตัวหนา: คะแนน**ต่ำสุด**ของคนเดียวกัน และคะแนน**สูงสุด**ของคนละคน")
        add("ถ้าตัวแรกมากกว่าตัวหลัง แปลว่าแยกกันได้สะอาด")
        add("")

    rec = data["recommendation"]
    add("## ค่าที่แนะนำ")
    add("")
    if not rec["ok"]:
        add(f"**ยังสรุปไม่ได้** — {rec['reason']}")
        add("")
    else:
        add("```")
        add(f"FACE_MATCH_THRESHOLD={rec['match_threshold']}")
        add(f"FACE_REVIEW_MIN={rec['review_min']}")
        add("```")
        add("")
        add(f"ที่มา: {rec['rule']}")
        add("")
        if rec["separated"]:
            add(f"คนเดียวกันต่ำสุด **{rec['worst_genuine']}** > คนละคนสูงสุด **{rec['best_impostor']}** "
                "— แยกกันได้สะอาดในชุดข้อมูลนี้")
        else:
            add(f"⚠️ **คะแนนซ้อนทับกัน** — คนเดียวกันต่ำสุด {rec['worst_genuine']} "
                f"ไม่ได้มากกว่าคนละคนสูงสุด {rec['best_impostor']}")
            add("")
            add("ไม่มีเกณฑ์ใดแยกภาพชุดนี้ได้หมด ค่าที่ให้คือจุดที่ผิดพลาดสองด้านเท่ากัน")
            add("ควรเก็บภาพเพิ่ม หรือปรับสภาพแสง/ระยะ/มุมกล้องก่อนใช้งานจริง")
        add("")

    add("## ตารางอัตราความผิดพลาด")
    add("")
    add("- **FAR** = คนละคนแต่ระบบบอกว่าตรง (ปล่อยคนสวมสิทธิ์ผ่าน)")
    add("- **FRR** = คนเดียวกันแต่ระบบบอกว่าไม่ตรง (กันคนที่ถูกต้องออก)")
    add("")
    if not data["sweep"]:
        add("_ยังคำนวณไม่ได้ ต้องมีอย่างน้อย 2 คน คนละ 2 ภาพ_")
        add("")
    add("| เกณฑ์ | FAR | FRR |")
    add("|---|---|---|")
    for row in data["sweep"]:
        if row["threshold"] < data["sweep_from"] or row["threshold"] > data["sweep_to"]:
            continue
        marker = " ←" if abs(row["threshold"] - data["recommendation"].get("match_threshold", -1)) < 1e-9 else ""
        add(f"| {row['threshold']:.3f} | {row['far']:.1%} | {row['frr']:.1%}{marker} |")
    add("")

    add("## ข้อจำกัดของตัวเลขชุดนี้")
    add("")
    genuine_count = data["genuine"]["count"] if data["genuine"] else 0
    impostor_count = data["impostor"]["count"] if data["impostor"] else 0
    if impostor_count:
        add(f"- FAR วัดจากคู่ภาพคนละคนเพียง **{impostor_count}** คู่ "
            f"ความละเอียดที่วัดได้จึงหยาบระดับ **{1 / impostor_count:.1%}** เท่านั้น "
            "ถ้าต้องการอ้าง FAR ระดับ 1 ใน 1,000 ต้องมีคู่ภาพหลักพัน")
    else:
        add("- **ไม่มีคู่ภาพคนละคนเลย** จึงวัด FAR ไม่ได้ ต้องมีอย่างน้อย 2 คน")
    if genuine_count:
        add(f"- FRR วัดจากคู่ภาพคนเดียวกัน **{genuine_count}** คู่")
    else:
        add("- **ไม่มีคู่ภาพคนเดียวกันเลย** จึงวัด FRR ไม่ได้ ต้องมีอย่างน้อยคนละ 2 ภาพ")
    add("- ภาพที่ใช้ควรมาจากกล้องและสภาพแสงแบบเดียวกับตอนใช้งานจริง "
        "ถ้าเก็บภาพด้วยมือถือแต่ใช้งานจริงด้วยเว็บแคมในห้องมืด ตัวเลขนี้จะมองโลกในแง่ดีเกินไป")
    add("- ค่านี้ใช้ได้กับโมเดลชุดปัจจุบันเท่านั้น เปลี่ยนโมเดลเมื่อไรต้องปรับเทียบใหม่ทั้งหมด")
    add("")

    add("## นำไปใช้")
    add("")
    add("1. ตั้ง `FACE_MATCH_THRESHOLD` กับ `FACE_REVIEW_MIN` ใน `.env` "
        "แล้ว `docker compose up -d`")
    add("2. ตั้งค่าเดียวกันในระบบที่เรียกใช้บริการนี้ด้วย — และให้ระบบนั้น"
        "ส่ง threshold มากับ `/verify` ทุกครั้ง ถ้าสองฝั่งตั้งไม่ตรงกัน "
        "บันทึกจะเขียนเลขหนึ่งแต่ตัดสินด้วยอีกเลขหนึ่ง")
    add("3. ผลตรวจเก่าไม่ถูกตีความใหม่ ตราบใดที่ระบบฝั่งผู้เรียกเก็บ threshold "
        "ที่ใช้จริงไว้กับผลแต่ละครั้ง (`/verify` คืนค่านั้นมาใน `thresholds`)")
    add("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--faces", default=str(Path(__file__).parent / "tests" / "faces"))
    parser.add_argument("--out", default="/app/reports/CALIBRATION.md")
    parser.add_argument("--json", default=None, help="also write the raw numbers here")
    args = parser.parse_args()

    faces = Path(args.faces)
    if not faces.is_dir():
        print(f"no such directory: {faces}", file=sys.stderr)
        return 2

    by_person = collect_photos(faces)
    if not by_person:
        print(f"no images found in {faces}", file=sys.stderr)
        print("expected faces/<person>_<n>.jpg or faces/<person>/<anything>.jpg", file=sys.stderr)
        return 2

    print(f"reading {sum(len(v) for v in by_person.values())} photos "
          f"of {len(by_person)} people...")
    embeddings, photos = embed_all(by_person)

    for record in photos:
        if record["usable"]:
            print(f"  ok    {record['person']:<14} {record['file']:<28} "
                  f"det={record['det_score']} width={record['face_width_px']}px "
                  f"liveness={record['liveness']}")
        else:
            print(f"  SKIP  {record['person']:<14} {record['file']:<28} "
                  f"{record.get('problem')}")

    usable = [r for r in photos if r["usable"]]
    people_with_faces = {p for p, v in embeddings.items() if v}

    genuine_pairs, impostor_pairs = score_pairs(embeddings)
    genuine = [s for _, s in genuine_pairs]
    impostor = [s for _, s in impostor_pairs]

    rows = sweep(genuine, impostor) if (genuine and impostor) else []
    rec = recommend(genuine, impostor, rows)

    data = {
        "when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "model_pack": config.MODEL_PACK,
        "service_version": config.SERVICE_VERSION,
        "people": len(people_with_faces),
        "photos_total": len(photos),
        "photos_usable": len(usable),
        "unusable": [r for r in photos if not r["usable"]],
        "genuine": describe(genuine) if genuine else None,
        "impostor": describe(impostor) if impostor else None,
        "sweep": rows,
        "sweep_from": 0.20,
        "sweep_to": 0.55,
        "recommendation": rec,
        "photos": photos,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_report(out, data)
    print(f"\nwrote {out}")

    if args.json:
        Path(args.json).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    if not rec["ok"]:
        print(f"NOT ENOUGH DATA: {rec['reason']}")
        return 1

    print(f"  FACE_MATCH_THRESHOLD={rec['match_threshold']}")
    print(f"  FACE_REVIEW_MIN={rec['review_min']}")
    print(f"  ({rec['rule']})")
    if not rec["separated"]:
        print("\n  WARNING: the score distributions overlap. No threshold separates")
        print("  these photos cleanly — collect more, or fix the capture conditions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
