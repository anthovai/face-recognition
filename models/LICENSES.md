# โมเดลที่ใช้ และไลเซนส์

**ทุกตัวในโฟลเดอร์นี้ใช้เชิงพาณิชย์ได้** ถ้าจะเพิ่มโมเดลใหม่ ต้องบันทึกไลเซนส์ที่นี่ก่อน

| ไฟล์ | โมเดล | ที่มา | ไลเซนส์ | ใช้ทำอะไร | มากับแพ็กเกจ |
|---|---|---|---|---|---|
| `face_detection_yunet_2023mar.onnx` | YuNet | [opencv/opencv_zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) | MIT | ตรวจจับใบหน้า + 5 landmark | ดึงด้วย `fetch.sh` |
| `face_recognition_sface_2021dec.onnx` | SFace | [opencv/opencv_zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface) | Apache-2.0 | embedding 128 มิติ | ดึงด้วย `fetch.sh` |
| `2.7_80x80_MiniFASNetV2.onnx` | MiniFASNetV2 | [MiniVision Silent-Face-Anti-Spoofing](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing) | Apache-2.0 | liveness (ตรวจภาพปลอม) | ✅ อยู่ในโฟลเดอร์นี้แล้ว |
| `4_0_0_80x80_MiniFASNetV1SE.onnx` | MiniFASNetV1SE | เดียวกัน | Apache-2.0 | liveness | ✅ อยู่ในโฟลเดอร์นี้แล้ว |

สองไฟล์แรกไม่ได้แนบมาเพราะไฟล์ใหญ่ (SFace ~38 MB) และดึงจากต้นทางได้ตรงๆ
รัน `sh fetch.sh` ครั้งเดียวก่อนสตาร์ตครั้งแรก

สองไฟล์ MiniFASNet แนบมาด้วยเพราะต้นทางเผยแพร่เป็น PyTorch `.pth`
ไฟล์ ONNX ที่ให้มานี้แปลงไว้แล้ว — ไลเซนส์ Apache-2.0 อนุญาตให้ส่งต่อได้

## ที่ตั้งใจไม่ใช้

| โมเดล | เหตุผล |
|---|---|
| InsightFace `buffalo_l` / `antelopev2` | โค้ดเป็น MIT แต่**น้ำหนักโมเดลอนุญาตเฉพาะงานวิจัยที่ไม่ใช่เชิงพาณิชย์** ต้องซื้อไลเซนส์แยกถึงจะใช้ในงานขายได้ |
| YOLOv8 / YOLO11 (Ultralytics) | AGPL-3.0 — ลามถึงโค้ดฝั่งเซิร์ฟเวอร์ที่ให้บริการผ่านเน็ต |

ถ้าจะเปลี่ยนไปใช้ InsightFace เพราะความแม่นยำ ต้องติดต่อ
`recognition-oss-pack@insightface.ai` และเก็บสัญญาไว้ก่อน — ห้ามใส่กลับเข้ามาเงียบๆ
เพราะปัญหาไลเซนส์แบบนี้ไม่แสดงตัวจนกว่าจะถูกตรวจ

## ถ้าเปลี่ยนโมเดล embedding

Embedding ที่เก็บไว้เดิม **ใช้กับโมเดลใหม่ไม่ได้** — คนละปริภูมิเวกเตอร์
`/verify` จะตอบ `embedding_mismatch` ถ้ามิติไม่ตรง แต่ถ้ามิติบังเอิญตรงกัน
มันจะเทียบได้โดยไม่มีอะไรเตือน และผลที่ได้ไม่มีความหมาย
เปลี่ยนโมเดลเมื่อไหร่ ต้องให้ทุกคนลงทะเบียนใบหน้าใหม่ และต้องปรับ threshold ใหม่ด้วย
