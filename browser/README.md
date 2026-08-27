# Browser modules — เฝ้าดูพฤติกรรมระหว่างทำงาน

JavaScript ฝั่งเบราว์เซอร์ที่ทำงานคู่กับบริการ Face Recognition
ตรวจจับ **เม้าหยุดนิ่ง, ออกจากหน้าต่าง, สลับแท็บ, ออกจากเต็มจอ, ไม่พบคนหน้ากล้อง,
ใบหน้าไม่ตรง** แล้วหยุดสื่อ แสดงข้อความ และส่งบันทึกไปที่ระบบของคุณ

ไม่พึ่งไลบรารีใดเลย ไม่ต้อง build ใส่ `<script>` ได้ตรงๆ
รองรับทั้ง `<script>`, AMD และ CommonJS

---

## ⚠️ อ่านก่อน: กุญแจต้องไม่อยู่ในเบราว์เซอร์

โมดูลเหล่านี้**ไม่เคยเรียกบริการ Face Recognition โดยตรง** และไม่ควรเรียก
เพราะใครก็ตามที่ถือ `FACE_API_KEY` สามารถถามว่า "นี่คนเดียวกันไหม" กับรูปอะไรก็ได้

โครงสร้างที่ถูกต้อง:

```
เบราว์เซอร์ ──► backend ของคุณ ──► Face Recognition service
   (ไม่มีกุญแจ)      (ถือกุญแจ)          (:9000)
                    (บันทึกผล)
```

การบันทึกผลที่ฝั่งเซิร์ฟเวอร์สำคัญพอๆ กับกุญแจ — บันทึกที่เบราว์เซอร์เขียนเอง
คือบันทึกที่ผู้ถูกเฝ้าดูเป็นคนเขียน ซึ่งใช้เป็นหลักฐานไม่ได้

---

## ไฟล์

| ไฟล์ | ทำอะไร | พึ่งอะไร |
|---|---|---|
| `src/attention-monitor.js` | สมองของระบบ — ตัดสินว่าอะไรผิดปกติและทำอะไรต่อ | ไม่มี |
| `src/camera.js` | เปิดกล้อง จับภาพนิ่ง | ไม่มี |
| `src/lockdown.js` | บังคับเต็มจอ ปิดคลิกขวา ตรวจ devtools | ไม่มี |
| `src/strings.js` | ข้อความไทย/อังกฤษ | ไม่มี |
| `src/api.js` | **ตัวอย่าง** adapter ที่ยิงไป backend ของคุณ | ไม่มี |
| `proctor.css` | สไตล์ของ overlay และตัวนับถอยหลัง | — |
| `example/index.html` | ตัวอย่างรันได้จริง ใช้ api ปลอม | — |

---

## เริ่มใช้

```html
<link rel="stylesheet" href="proctor.css">
<script src="src/camera.js"></script>
<script src="src/strings.js"></script>
<script src="src/api.js"></script>
<script src="src/attention-monitor.js"></script>
```

```js
var camera = new Proctor.Camera(document.getElementById('preview'));

camera.start().then(function () {
    var monitor = new Proctor.AttentionMonitor({
        video: document.getElementById('lesson'),   // null ได้ ถ้าไม่มีสื่อ
        api: Proctor.createApi({
            baseUrl: '/api/proctor',                // endpoint ของคุณเอง
            sessionId: 'sitting-12345'
        }),
        strings: Proctor.strings.th,

        mouseIdleSeconds: 180,      // เม้านิ่งเกินนี้ = หยุด
        mouseIdleWarnSec: 10,       // เตือนล่วงหน้ากี่วินาที
        presenceSeconds: 120,       // ตรวจว่ามีคนหน้ากล้องทุกกี่วินาที
        presenceWarnSec: 5,         // ผ่อนผันก่อนตัดสินว่าไม่มีคน
        verifySeconds: 600,         // ตรวจว่าเป็นคนเดิมทุกกี่วินาที
        clickConfirmSeconds: 300,   // ให้กดยืนยันทุกกี่วินาที
        clickConfirmGraceSec: 30,
        randomClipsPerHour: 4,      // อัดคลิปสุ่มกี่ครั้งต่อชั่วโมง
        clipSeconds: 8,

        strictLockdown: false,      // true = ออกจากหน้าต่างแล้วจบเลย
        blurAllowance: 0,           // ยอมให้ออกจากหน้าต่างกี่ครั้งก่อนจบ
        desktopNotification: true,

        getSnapshot: function () { return camera.snapshot(); },
        getStream: function () { return camera.getStream(); },

        onTerminate: function (info) {
            window.location = '/finished?reason=' + info.type;
        }
    });

    monitor.start();
});
```

**ทุกค่าเป็นวินาที** ตั้ง `0` เพื่อปิดการตรวจนั้น

---

## สิ่งที่โมดูลจะบอกคุณ

`api.logEvent(type, detail, videotime)` ถูกเรียกด้วย `type` เหล่านี้

| กลุ่ม | type |
|---|---|
| วงจรชีวิต | `monitor_started`, `monitor_stopped`, `session_terminated` |
| ออกจากหน้าจอ | `tab_hidden`, `window_blur`, `fullscreen_exit`, `focus_loss_ignored` |
| เม้า/คีย์บอร์ด | `mouse_idle`, `click_confirm_ok`, `click_confirm_timeout`, `resumed` |
| กล้อง | `presence_ok`, `presence_lost`, `presence_restored`, `face_absent`, `multiple_faces`, `presence_error` |
| ตัวตน | `identity_check`, `face_mismatch`, `face_review`, `verify_error` |
| หลักฐาน | `clip_started`, `clip_uploaded`, `clip_error`, `clip_skipped` |
| lockdown | `devtools_suspected`, `context_menu`, `copy_attempt`, `paste_attempt`, `print_screen` |

`presence_error` กับ `verify_error` **สำคัญกว่าที่คิด** — หมายถึงการตรวจ*ทำไม่ได้*
ไม่ใช่*ผ่าน* ถ้าบันทึกมันเป็น "ผ่าน" บริการที่ตายอยู่จะดูเหมือนห้องที่ทุกคนตั้งใจเรียน

---

## สัญญาของ `api`

โมดูลเรียกสี่อย่างนี้ ทุกอันต้องคืน Promise และห้าม throw ทันที

```js
analyze(blob)                    // -> {ok, present, warning, reason}
verify(blob, storeEvidence)      // -> {ok, decision, similarity, errorcode}
storeEvidence(kind, reason, blob)// -> {ok, evidenceid}
logEvent(type, detail, videotime)// -> Promise (ค่าที่คืนไม่ถูกใช้)
```

`analyze` และ `verify` ให้ backend คุณ proxy ไปที่ Face Recognition service
โดยเติม `X-Face-Key` ให้ ส่วน `decision` คือ `pass` / `review` / `fail` / `fail_liveness`

ดู `src/api.js` เป็นตัวอย่างที่ใช้ได้เลย แก้ path ให้ตรงกับ backend ของคุณ

---

## ลองดู

```bash
python -m http.server 8080
```

เปิด `http://localhost:8080/example/` แล้วกด "เริ่มเฝ้าดู" อย่าขยับเม้า
จะเห็นตัวนับถอยหลัง แล้ว overlay ขึ้น พร้อม event ที่บันทึกไว้ด้านล่าง

ตัวอย่างใช้ api ปลอมที่ไม่เรียกเซิร์ฟเวอร์เลย จึงลองได้โดยไม่ต้องมี backend

---

## ข้อจำกัดที่ต้องบอกลูกค้าตรงๆ

**หน้าเว็บไม่มีสิทธิ์ระดับระบบปฏิบัติการ** Alt+Tab, ปุ่ม Windows, จอที่สอง
และมือถือที่วางอยู่ข้างๆ — ห้ามไม่ได้ สิ่งที่ทำได้คือ**ตรวจจับและบันทึก**
ถ้าต้องการล็อกดาวน์ระดับเครื่องจริงๆ ต้องใช้ Safe Exam Browser หรือแอป kiosk

**`devtools_suspected` เป็นการเดา** ดูจากขนาดหน้าต่างที่เปลี่ยนผิดปกติ
ซึ่งการต่อจอที่สองก็ทำให้เกิดได้ อย่าตัดสินใครจากสัญญาณนี้เพียงอย่างเดียว

**เบราว์เซอร์บล็อกกล้องได้เสมอ** ต้องมีทางเดินต่อเมื่อผู้ใช้ปฏิเสธ
`camera.js` คืนเหตุผลมาเป็นคำเดียว (`denied` / `busy` / `nocamera`)
เพื่อให้คุณบอกผู้ใช้ได้ตรงจุด แทนที่จะโทษแสงสว่างทุกกรณี

**ความยินยอมเป็นหน้าที่ของคุณ** โมดูลเหล่านี้เปิดกล้องเมื่อถูกสั่ง
ไม่ได้ถามใครก่อน ใบหน้าเป็นข้อมูลชีวมิติตาม PDPA ม.26 ต้องขอความยินยอม
โดยชัดแจ้ง**ก่อน**เปิดกล้อง และต้องบอกด้วยว่าเก็บอะไร นานเท่าไร
