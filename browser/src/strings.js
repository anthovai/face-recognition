// The words the person being watched actually reads.
//
// Kept apart from the logic so that changing what somebody is told does not
// mean editing the module that decides when to tell them. Pass your own object
// to AttentionMonitor; anything you leave out falls back to the key itself,
// which reads as a missing translation rather than as a blank overlay.
//
// {$a} is substituted with the number of seconds, in the two countdown lines.
//
// A note on the wording, since it is easy to undo by accident: these say what
// happened and what to do about it, and they do not accuse. "ไม่พบการเคลื่อนไหว"
// is a fact; "คุณไม่สนใจบทเรียน" is a verdict the software is in no position to
// reach, and the person on the other side of it has usually just answered the
// door.
(function (root, factory) {
    if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else if (typeof define === 'function' && define.amd) {
        define([], factory);
    } else {
        root.Proctor = root.Proctor || {};
        root.Proctor.strings = factory();
    }
}(typeof self !== 'undefined' ? self : this, function () {

    var th = {
        'notification:title': 'ระบบคุมสอบ',

        'countdown:idle': 'ไม่พบการเคลื่อนไหว จะหยุดในอีก {$a} วินาที',
        'countdown:presence': 'ไม่พบคุณหน้ากล้อง จะหยุดในอีก {$a} วินาที',

        'confirm:title': 'ยืนยันว่ายังอยู่',
        'confirm:body': 'กดปุ่มภายในเวลาที่กำหนด',
        'confirm:button': 'ยืนยัน',

        'paused:title': 'หยุดชั่วคราว',
        'paused:resume': 'เล่นต่อ',

        'terminated:title': 'จบการทำงานแล้ว',
        'terminated:close': 'ปิด',

        'violation:tab_hidden': 'สลับแท็บหรือย่อหน้าต่างระหว่างทำงาน',
        'violation:window_blur': 'ออกจากหน้าต่าง',
        'violation:fullscreen_exit': 'ออกจากโหมดเต็มจอ',
        'violation:devtools_suspected': 'ตรวจพบการเปิดเครื่องมือนักพัฒนา',
        'violation:click_confirm_timeout': 'ไม่ได้กดยืนยันในเวลาที่กำหนด',
        'violation:mouse_idle': 'ไม่มีการขยับเมาส์หรือใช้คีย์บอร์ดเป็นเวลานาน',
        'violation:face_absent': 'ไม่พบคุณหน้ากล้อง',
        'violation:multiple_faces': 'พบมากกว่าหนึ่งคนหน้ากล้อง กดเล่นต่อเมื่อเหลือคนเดียว',
        'violation:face_review': 'ยืนยันใบหน้าไม่ชัดเจน จัดหน้าให้อยู่กลางกล้องแล้วกดเล่นต่อ',
        'violation:fail': 'ใบหน้าไม่ตรงกับที่ลงทะเบียนไว้',
        'violation:fail_liveness': 'สงสัยการใช้ภาพถ่ายหรือวิดีโอแทนคนจริง'
    };

    var en = {
        'notification:title': 'Proctor',

        'countdown:idle': 'No activity detected. Pausing in {$a} seconds.',
        'countdown:presence': 'We cannot see you. Pausing in {$a} seconds.',

        'confirm:title': 'Confirm you are still there',
        'confirm:body': 'Press the button before the time runs out.',
        'confirm:button': 'Confirm',

        'paused:title': 'Paused',
        'paused:resume': 'Resume',

        'terminated:title': 'Session ended',
        'terminated:close': 'Close',

        'violation:tab_hidden': 'Switched tab or minimised the window.',
        'violation:window_blur': 'Left the window.',
        'violation:fullscreen_exit': 'Left fullscreen.',
        'violation:devtools_suspected': 'Developer tools appear to be open.',
        'violation:click_confirm_timeout': 'The confirmation was not pressed in time.',
        'violation:mouse_idle': 'No mouse or keyboard activity for some time.',
        'violation:face_absent': 'We cannot see you at the camera.',
        'violation:multiple_faces': 'More than one person is visible. Resume when you are alone.',
        'violation:face_review': 'The identity check was inconclusive. Centre your face and resume.',
        'violation:fail': 'The face does not match the enrolled one.',
        'violation:fail_liveness': 'A photograph or video may be in front of the camera.'
    };

    return {th: th, en: en};
}));
