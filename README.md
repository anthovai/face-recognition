# Face Recognition Service

> **ซอฟต์แวร์มีสัญญาอนุญาต** ใช้ภายในองค์กรได้ไม่จำกัด แก้ไขได้ แต่**ห้ามส่งต่อหรือเปิดเผยซอร์สโค้ดต่อบุคคลภายนอก** อ่าน [LICENSE](LICENSE) ก่อนใช้งาน
> ไฟล์โมเดลใน `models/` เป็น MIT/Apache-2.0 ซึ่งมีเงื่อนไขของตัวเอง — ดู [models/LICENSES.md](models/LICENSES.md)

บริการตรวจจับใบหน้า ลงทะเบียนใบหน้า เทียบตัวตน และตรวจภาพปลอม (liveness)
เรียกใช้ผ่าน HTTP ไม่ผูกกับระบบใดระบบหนึ่ง

**ไม่เก็บอะไรลงดิสก์เลย** ไม่เก็บรูป ไม่เก็บ embedding ไม่เก็บรหัสผู้ใช้
ไม่จำอะไรข้ามการเรียกแต่ละครั้ง สิ่งที่ต้องเก็บคือ embedding กับผลการตัดสิน
และทั้งสองอย่างเป็นของระบบฝั่งคุณ — ที่ซึ่งกฎเรื่องความยินยอมและระยะเวลาเก็บข้อมูล
ของคุณบังคับใช้ได้จริง แทนที่จะถูกบริการนี้กำหนดให้

---

## เริ่มใช้งาน

```bash
sh models/fetch.sh
```

```bash
FACE_API_KEY=ตั้งรหัสลับของคุณเอง docker compose up -d
```

```bash
curl -s localhost:9000/health
```

ถ้า `liveness_available` เป็น `true` และ `models_present` มี 4 ไฟล์ แปลว่าพร้อมใช้งาน

---

## API

ทุก endpoint ยกเว้น `/health` ต้องส่ง header `X-Face-Key: <FACE_API_KEY>`
ถ้าไม่ตรงจะได้ `401 invalid_api_key`

รูปส่งเป็น `multipart/form-data` รองรับ JPEG/PNG ขนาดไม่เกิน 8 MB (ปรับได้ที่ `FACE_MAX_IMAGE_BYTES`)

### `GET /health`

ไม่ต้องใช้กุญแจ บอกว่าโมเดลไหนโหลดสำเร็จ และ threshold ที่ใช้อยู่คือเท่าไร

```json
{
  "ok": true,
  "service_version": "1.0.0",
  "model_pack": "yunet+sface",
  "models_present": ["2.7_80x80_MiniFASNetV2.onnx", "..."],
  "liveness_available": true,
  "thresholds": {"match": 0.363, "review_min": 0.3, "liveness": 0.6}
}
```

`liveness_available: false` หมายถึงไฟล์ MiniFASNet หายไป และบริการยังตอบ `/verify`
ต่อได้โดย**ไม่ตรวจภาพปลอม** — ต้องเฝ้าค่านี้ ไม่ใช่ดูแค่ว่า service ยังตอบอยู่ไหม

### `POST /analyze` — มีคนอยู่ไหม หันหน้าไปทางไหน ภาพจริงหรือปลอม

ออกแบบมาให้ยิงถี่ๆ ได้ (เช่น ท้าทายให้หันหน้าตามคำสั่ง วินาทีละหลายครั้ง)
**ไม่มีหน้าคนไม่ถือว่าเป็น error** — เป็นคำตอบปกติของ endpoint นี้

```bash
curl -s localhost:9000/analyze \
  -H "X-Face-Key: $FACE_API_KEY" \
  -F image=@frame.jpg
```

```json
{
  "ok": true,
  "present": true,
  "det_score": 0.9312,
  "bbox": [120.5, 88.0, 240.0, 240.0],
  "pose": {"pitch": -2.1, "yaw": 18.4, "roll": 0.9},
  "liveness": {"evaluated": true, "live": true, "score": 0.87}
}
```

ไม่พบหน้า → `{"ok": true, "present": false, "reason": "no_face"}`
(`reason` เป็น `no_face` หรือ `face_too_small`)
พบหลายหน้า → `{"ok": true, "present": true, "warning": "multiple_faces"}`

**ทิศทางของ `yaw`** วัดจากภาพดิบที่ส่งมา ไม่ใช่ภาพที่กลับด้านแล้ว
หันไปทางซ้ายของตัวเอง = yaw เป็นบวก / หันไปทางขวาของตัวเอง = yaw เป็นลบ
ภาพพรีวิวบนจอควรกลับด้านให้ดูเป็นธรรมชาติ แต่ต้องส่งภาพดิบมาวิเคราะห์
ไม่งั้นทิศจะสลับกัน

### `POST /embed` — ลงทะเบียนใบหน้า

รูปเข้าหนึ่งใบ ได้ embedding ออกไปหนึ่งชุด **เก็บ embedding ไว้ ไม่ต้องเก็บรูป**
เพราะ embedding ย้อนกลับเป็นใบหน้าไม่ได้ และเป็นสิ่งเดียวที่ `/verify` ต้องใช้

```bash
curl -s localhost:9000/embed \
  -H "X-Face-Key: $FACE_API_KEY" \
  -F image=@portrait.jpg
```

```json
{
  "ok": true,
  "embedding": "j7yQvL0AAA...",   // base64 ของ float32 128 ตัว
  "dimensions": 128,
  "det_score": 0.9412,
  "liveness": {"evaluated": true, "live": true, "score": 0.91}
}
```

ควรปฏิเสธการลงทะเบียนถ้า `liveness.live` เป็น `false` — ไม่งั้นคนถ่ายรูปจากจอมือถือ
มาลงทะเบียนได้ และหลังจากนั้น**ทุกครั้งที่เทียบจะผ่าน** เพราะเทียบกับรูปปลอมนั้นเอง

### `POST /verify` — คนนี้ใช่คนเดิมไหม

```bash
curl -s localhost:9000/verify \
  -H "X-Face-Key: $FACE_API_KEY" \
  -F live_image=@frame.jpg \
  -F reference_embedding="$STORED_EMBEDDING" \
  -F match_threshold=0.363 \
  -F review_min=0.30
```

```json
{
  "ok": true,
  "decision": "pass",
  "similarity": 0.5821,
  "thresholds": {"match": 0.363, "review_min": 0.3, "liveness": 0.6},
  "liveness": {"evaluated": true, "live": true, "score": 0.88},
  "det_score": 0.9187
}
```

| `decision` | ความหมาย |
|---|---|
| `pass` | similarity ≥ match_threshold |
| `review` | อยู่ระหว่าง review_min กับ match_threshold — ให้คนดู อย่าตัดสินอัตโนมัติ |
| `fail` | ต่ำกว่า review_min |
| `fail_liveness` | ตรวจเจอภาพปลอม — **ทับผลการเทียบเสมอ** ต่อให้ similarity สูงแค่ไหน |

**ควรส่ง threshold มาเองทุกครั้ง** ระบบฝั่งคุณคือที่ที่ผู้ดูแลตั้งค่าและบันทึกว่า
ตัดสินด้วยเลขอะไร ถ้าไม่ส่งมา บริการจะใช้ค่าของตัวเอง — และวันที่สองฝั่งตั้งไม่ตรงกัน
บันทึกจะเขียนเลขหนึ่งแต่ตัดสินด้วยอีกเลขหนึ่ง โดยที่บันทึกคือสิ่งเดียวที่คนอ่านทีหลัง

ค่าที่ใช้จริงตอบกลับมาใน `thresholds` — เก็บค่านั้น ไม่ใช่ค่าที่คุณหวังว่าจะถูกใช้

---

## รหัสข้อผิดพลาด

ทุกความผิดพลาดตอบเป็น `{"ok": false, "error": {"code": "...", "message": "..."}}`

| code | สถานะ | หมายถึง |
|---|---|---|
| `invalid_api_key` | 401 | `X-Face-Key` ไม่ตรงหรือไม่ได้ส่งมา |
| `no_face` | 422 | ไม่พบใบหน้า (`/analyze` ตอบเป็น `present: false` แทน) |
| `face_too_small` | 422 | เจอหน้าแต่เล็กกว่า `FACE_MIN_SIZE` พิกเซล |
| `multiple_faces` | 422 | มีหน้ามากกว่าหนึ่ง (`/analyze` ตอบเป็น `warning` แทน) |
| `invalid_image` | 422 | ถอดรหัสภาพไม่ได้ |
| `image_too_large` | 422 | เกิน `FACE_MAX_IMAGE_BYTES` |
| `invalid_embedding` | 422 | `reference_embedding` ไม่ใช่ base64 ที่ถูกต้อง หรือว่างเปล่า |
| `embedding_mismatch` | 422 | มิติไม่ตรงกับที่โมเดลปัจจุบันสร้าง — ต้องลงทะเบียนใหม่ |
| `invalid_threshold` | 422 | threshold ไม่ใช่ตัวเลข อยู่นอกช่วง −1..1 หรือ review_min สูงกว่า match |

---

## การตั้งค่า

| ตัวแปร | ค่าตั้งต้น | ทำอะไร |
|---|---|---|
| `FACE_API_KEY` | *(ว่าง = ปิดการตรวจ)* | รหัสลับที่ผู้เรียกต้องส่งมาใน `X-Face-Key` |
| `FACE_MATCH_THRESHOLD` | `0.363` | ผ่านเมื่อ similarity ถึงค่านี้ |
| `FACE_REVIEW_MIN` | `0.30` | ต่ำกว่านี้คือ fail ระหว่างสองค่าคือ review |
| `FACE_LIVENESS_THRESHOLD` | `0.60` | คะแนน liveness ที่ถือว่าเป็นคนจริง |
| `FACE_DET_SCORE` | `0.80` | ความมั่นใจขั้นต่ำของตัวตรวจจับ |
| `FACE_MIN_SIZE` | `80` | ขนาดหน้าขั้นต่ำเป็นพิกเซล |
| `FACE_MAX_IMAGE_BYTES` | `8388608` | ขนาดรูปสูงสุด |
| `FACE_MODELS_DIR` | `./models` | ที่อยู่ของไฟล์โมเดล |

`FACE_API_KEY` ว่าง = **ไม่ตรวจสิทธิ์เลย** สะดวกตอนทดสอบบนเครื่องตัวเอง
และผิดในทุกที่นอกจากนั้น เพราะบริการนี้ตอบคำถามว่า "นี่คนเดียวกันไหม"
กับรูปอะไรก็ได้ที่ส่งมา

---

## การปรับ threshold

**ค่าที่ให้มาไม่ใช่ค่าที่ปรับแล้ว** `0.363` เป็นค่าอ้างอิงของ OpenCV เอง
ใช้เป็นจุดเริ่มต้นเท่านั้น ต้องวัดกับรูปลงทะเบียนจริงของคุณก่อนขึ้นใช้งานจริง
เพราะกล้อง แสง และกลุ่มคนของแต่ละที่ไม่เหมือนกัน

```bash
docker compose run --rm face python calibrate.py
```

สคริปต์ต้องการรูปใน `tests/faces/` — โฟลเดอร์ละหนึ่งคน อย่างน้อยคนละ 2 รูป
มันจะกวาดค่า threshold แล้วรายงานว่าแต่ละค่าให้ false accept / false reject เท่าไร

จำนวนรูปกำหนดว่าผลเชื่อถือได้แค่ไหน — คน 25 คนแยกความต่างได้ราว 4 จุดเปอร์เซ็นต์
ไม่ละเอียดกว่านั้น อย่าอ่านทศนิยมตำแหน่งที่สามจากข้อมูลชุดเล็ก

`calibrate_detection.py` ทำแบบเดียวกันกับ `FACE_DET_SCORE`
`bench_load.py` วัดว่ารับโหลดพร้อมกันได้เท่าไร

**รูปใบหน้าจริงห้ามเข้า repository** `.gitignore` กัน `tests/faces/` ไว้แล้ว

---

## ข้อควรรู้ก่อนขึ้นใช้งานจริง

**liveness ไม่ใช่การรับประกัน** MiniFASNet จับภาพถ่ายจากจอและรูปพิมพ์ได้ดี
แต่ไม่ได้กันหน้ากากคุณภาพสูงหรือ deepfake ถ้าความเสี่ยงถึงระดับนั้น
ต้องมีคนดูประกอบ

**`review` มีไว้ให้คนตัดสิน** ไม่ใช่ค่ากลางที่จะปัดขึ้นหรือลงเอง
ถ้าระบบฝั่งคุณปัด `review` เป็น `pass` อัตโนมัติ ก็เท่ากับลด threshold ลงมาที่
`review_min` โดยที่บันทึกยังเขียนว่าใช้ `match_threshold` — ซึ่งอธิบายทีหลังไม่ได้

**เก็บบันทึกทุกการตัดสิน** อย่างน้อย: similarity, threshold ที่ใช้จริง, decision,
ผล liveness และเวลา บริการนี้ไม่เก็บให้ และคนที่จะโต้แย้งผลในอีกหกเดือน
มีสิทธิ์รู้ว่าตอนนั้นใช้กฎอะไรตัดสิน

**ใบหน้าเป็นข้อมูลชีวมิติ** อยู่ภายใต้ PDPA มาตรา 26 (และ GDPR มาตรา 9
ถ้ามีผู้ใช้ในยุโรป) ต้องมีความยินยอมโดยชัดแจ้งก่อนเก็บ ต้องบอกว่าเก็บนานเท่าไร
และต้องลบได้จริงเมื่อถูกขอ ทั้งหมดนี้เป็นหน้าที่ของระบบฝั่งคุณ เพราะบริการนี้
ไม่ได้เก็บอะไรไว้ให้ลบ

**อย่าเปิดพอร์ตสู่อินเทอร์เน็ต** `docker-compose.yml` ผูกกับ loopback ไว้แล้ว
ถ้าต้องเรียกข้ามเครื่อง ให้อยู่หลัง reverse proxy ที่ทำ TLS และจำกัด IP ต้นทาง
API key อย่างเดียวไม่พอเมื่อคำขอวิ่งผ่านเน็ตแบบไม่เข้ารหัส

---

## ทดสอบ

```bash
docker compose run --rm face python -m pytest tests -q
```

ชุดทดสอบครอบคลุมตรรกะการตัดสิน การคำนวณ pose การจัดการภาพเสีย และเส้นแบ่ง
ของ threshold โดยไม่ต้องใช้รูปใบหน้าจริง

---

## โครงสร้าง

```
app/config.py        ค่าตั้งทั้งหมด อ่านจาก environment
app/face_engine.py   ตรวจจับ จัดตำแหน่ง embedding เทียบความเหมือน คำนวณ pose
app/liveness.py      MiniFASNet — ตรวจภาพปลอม
app/main.py          HTTP API
models/              น้ำหนักโมเดล + LICENSES.md (อ่านก่อนเปลี่ยนโมเดล)
calibrate.py         ปรับ match threshold กับรูปจริงของคุณ
```

Python 3.12, FastAPI, OpenCV (headless), ONNX Runtime — CPU ล้วน ไม่ต้องใช้ GPU
