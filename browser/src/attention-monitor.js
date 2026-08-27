// AttentionMonitor - watches a person while they work, and enforces a policy.
//
// Six signals, each with a consequence:
//
//  1. Tab/window    switching tab, minimising, leaving fullscreen
//                   -> pause whatever is playing, raise an OS notification
//                   -> strict mode ends the session
//  2. Presence      every N seconds, is anyone in front of the camera
//  3. Identity      every M seconds, is it still the same person
//  4. Click-confirm every N seconds the person must confirm they are there
//  5. Mouse idle    no input for N seconds -> pause
//  6. Random clip   short camera clips at unpredictable times, kept as evidence
//
// This module decides WHEN something has gone wrong and what appears on
// screen. It never talks to a server itself: every call goes through the `api`
// object you pass in, and every piece of text through `strings`. That is what
// makes it portable, and it is also what keeps the face service key out of the
// browser - `api` is yours to implement against your own backend.
//
// Known limit, stated rather than papered over: a web page has no operating
// system privileges. Alt+Tab, a second monitor and a phone on the desk cannot
// be prevented. What this does is detect and record.
(function (root, factory) {
    if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else if (typeof define === 'function' && define.amd) {
        define([], factory);
    } else {
        root.Proctor = root.Proctor || {};
        root.Proctor.AttentionMonitor = factory();
    }
}(typeof self !== 'undefined' ? self : this, function () {

    var ACTIVITY_EVENTS = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'wheel'];

    /**
     * @param {Object} opts
     * @param {HTMLVideoElement} opts.video the lesson video to police
     * @param {Number} opts.contextid where events and evidence are recorded
     * @param {Function} opts.getSnapshot returns Promise<Blob> of a camera frame
     * @param {Function} [opts.getStream] returns the MediaStream, for clips
     * @param {Function} [opts.onTerminate] called when the session is cut short
     */
    var AttentionMonitor = function(opts) {
        // Optional. A quiz attempt has no lesson to pause, and used to be
        // handed a detached <video> so that pause() would be a harmless
        // no-op. It was not harmless: a video element that has never played
        // reports paused === true forever, and _tick skips every timed check
        // while the lesson is paused — so presence, identity and idle never
        // ran for the whole of an exam. Absence is now stated rather than
        // faked, and the checks that do not need a video keep running.
        this.video = opts.video || null;

        // Everything this module cannot do for itself.
        //
        // `api` carries the four calls it makes - analyze, verify,
        // storeEvidence, logEvent - and it is yours to write, because only
        // your backend may hold the face service key, and only you know which
        // sitting a piece of evidence belongs to. api.js has a reference
        // implementation and the contract each call must honour.
        this.api = opts.api || {};
        // Text shown to the person being watched. Defaults are Thai; pass an
        // object of your own to change the wording or the language.
        this.strings = opts.strings || {};
        // Where an error inside a promise goes. Swallowing them silently
        // would be wrong: these are the failures nobody else sees.
        this.onError = opts.onError || function (error) {
            if (typeof console !== 'undefined') {
                console.error('[proctor]', error);
            }
        };
        this.getSnapshot = opts.getSnapshot || null;
        this.getStream = opts.getStream || null;
        this.onTerminate = opts.onTerminate || function() {};

        // Seconds everywhere. The settings, the policy snapshot, the
        // countdown on screen and this all speak the same unit now; when they
        // did not, half a minute was typed as 0.5 into a box whose label said
        // minutes, and the reader had to do arithmetic to know what the
        // countdown would say.
        var seconds = function(value, fallback) {
            return (value === undefined ? fallback : value) * 1000;
        };
        this.clickConfirmMs = seconds(opts.clickConfirmSeconds, 300);
        this.clickConfirmGraceMs = seconds(opts.clickConfirmGraceSec, 30);
        this.mouseIdleMs = seconds(opts.mouseIdleSeconds, 180);
        this.presenceMs = seconds(opts.presenceSeconds, 120);
        this.verifyMs = seconds(opts.verifySeconds, 600);

        // How long before a pause the learner is shown a running countdown.
        // Idle merely displays it inside the last stretch of a threshold that
        // fires at the same instant it always did. Presence is different: 0
        // reproduces the old behaviour of pausing on the first bad frame,
        // which is what the tests that do not pass this option still expect.
        this.mouseIdleWarnMs = seconds(opts.mouseIdleWarnSec, 10);
        this.presenceWarnMs = seconds(opts.presenceWarnSec, 5);

        this.strictLockdown = !!opts.strictLockdown;
        this.blurAllowance = opts.blurAllowance === undefined ? 0 : opts.blurAllowance;
        this.desktopNotification = opts.desktopNotification !== false;
        this.storeSnapshots = !!opts.storeSnapshots;
        this.identityEnabled = opts.identityEnabled !== false;

        this.clipsPerHour = opts.randomClipsPerHour === undefined ? 0 : opts.randomClipsPerHour;
        this.clipMs = (opts.clipSeconds === undefined ? 8 : opts.clipSeconds) * 1000;

        this._lastActivity = Date.now();
        this._lastConfirm = Date.now();
        this._lastPresence = Date.now();
        this._lastVerify = Date.now();
        this._confirmPending = false;
        this._confirmDeadline = 0;
        this._blurCount = 0;
        this._running = false;
        this._terminated = false;
        this._recording = false;
        this._overlay = null;
        this._nextClipAt = 0;
        this._presenceGracing = false;
        this._countdownEl = null;
        this._countdownType = null;
        // True only while our own notification prompt is unanswered.
        this._awaitingPermission = false;
    };

    /* ---------- the lesson, which may not exist ---------- */

    AttentionMonitor.prototype._pause = function() {
        if (this.video) {
            this.video.pause();
        }
    };

    AttentionMonitor.prototype._play = function() {
        if (this.video) {
            this.video.play();
        }
    };

    /**
     * Is the learner supposed to be watching something right now?
     *
     * True when there is no lesson at all: an exam has nothing to pause and
     * nothing to resume, so every check applies for as long as it is open.
     *
     * @return {Boolean}
     */
    AttentionMonitor.prototype._underway = function() {
        return !this.video || !this.video.paused;
    };

    /**
     * Did we cause this focus loss ourselves, by asking for permission?
     *
     * Recorded rather than silently dropped. A gap in the trail that nobody
     * explained is the thing an auditor cannot rule on later, and "the
     * proctor's own prompt took the focus" is a better answer than either
     * blaming the learner or leaving a hole.
     *
     * @param {String} type what would have been recorded
     * @return {Boolean} true if it was ours and should not count
     */
    AttentionMonitor.prototype._ownPrompt = function(type) {
        if (!this._awaitingPermission) {
            return false;
        }
        this._log('focus_loss_ignored', {would_have_been: type,
            reason: 'notification_permission_prompt'});
        return true;
    };

    /* ---------- lifecycle ---------- */

    AttentionMonitor.prototype.start = function() {
        if (this._running) {
            return;
        }
        var self = this;
        this._running = true;
        this._terminated = false;
        var now = Date.now();
        this._lastActivity = now;
        this._lastConfirm = now;
        this._lastPresence = now;
        this._lastVerify = now;
        this._blurCount = 0;
        this._scheduleNextClip(now);

        // Asking for notification permission takes the focus away from the
        // page, and taking the focus away from the page is the thing this
        // module punishes. In strict mode with no allowance that ended the
        // sitting about two seconds after it opened, blaming the learner for
        // a prompt we put up ourselves — and the audit trail recorded it as
        // them walking out.
        //
        // The flag is only raised while our own prompt is unanswered, so a
        // browser that has already been told yes or no (every run after the
        // first) clears it on the next microtask and polices focus normally.
        if (this.desktopNotification) {
            this._awaitingPermission = true;
            this.requestNotificationPermission().then(function(granted) {
                self._awaitingPermission = false;
                return granted;
            }).catch(function() {
                self._awaitingPermission = false;
                return false;
            });
        }

        this._onActivity = function() {
            self._lastActivity = Date.now();
        };
        ACTIVITY_EVENTS.forEach(function(name) {
            document.addEventListener(name, self._onActivity, {passive: true});
        });

        // Guarded here rather than inside _onFocusLoss, so that a violation
        // the lockdown module reports — leaving fullscreen, say — is still
        // acted on while the prompt is up. Those do not come from our prompt.
        this._onVisibility = function() {
            if (document.hidden && !self._ownPrompt('tab_hidden')) {
                self._onFocusLoss('tab_hidden');
            }
        };
        this._onBlur = function() {
            if (!self._ownPrompt('window_blur')) {
                self._onFocusLoss('window_blur');
            }
        };
        document.addEventListener('visibilitychange', this._onVisibility);
        window.addEventListener('blur', this._onBlur);

        this._timer = setInterval(function() {
            self._tick();
        }, 1000);

        this._log('monitor_started', {
            strict: this.strictLockdown,
            // Seconds, like every other interval in this system now. The
            // audit trail is read alongside the settings page, and one of them
            // quoting minutes while the other quotes seconds is how somebody
            // reads 3 and thinks they know what happened.
            verify_seconds: this.verifyMs / 1000,
            presence_seconds: this.presenceMs / 1000,
            clips_per_hour: this.clipsPerHour
        });
    };

    AttentionMonitor.prototype.stop = function() {
        if (!this._running) {
            return;
        }
        var self = this;
        this._running = false;
        clearInterval(this._timer);
        ACTIVITY_EVENTS.forEach(function(name) {
            document.removeEventListener(name, self._onActivity);
        });
        document.removeEventListener('visibilitychange', this._onVisibility);
        window.removeEventListener('blur', this._onBlur);
        this._stopRecording();
        this._removeOverlay();
        this._presenceGracing = false;
        this._hideCountdown();
        this._log('monitor_stopped', {});
    };

    /** Lets the lockdown module fold its violations into the same log. */
    AttentionMonitor.prototype.reportViolation = function(type, detail) {
        if (type === 'fullscreen_exit') {
            this._onFocusLoss('fullscreen_exit');
            return;
        }
        this._log(type, detail || {});
        if (this.strictLockdown && type === 'devtools_suspected') {
            this._terminate('devtools_suspected');
        }
    };

    /* ---------- focus loss ---------- */

    AttentionMonitor.prototype._onFocusLoss = function(type) {
        var self = this;
        if (!this._running || this._terminated) {
            return;
        }
        this._presenceGracing = false;
        this._hideCountdown();
        this._pause();
        this._blurCount += 1;
        this._log(type, {occurrence: this._blurCount});
        this._captureEvidence('violation_' + type);

        var message = this._text('violation:' + type);
        this._notify(message);
        if (this.strictLockdown && this._blurCount > this.blurAllowance) {
            this._terminate(type);
            return;
        }
        this._interruptOverlay(type, message);
    };

    AttentionMonitor.prototype._terminate = function(type) {
        var self = this;
        if (this._terminated) {
            return;
        }
        this._terminated = true;
        this._presenceGracing = false;
        this._hideCountdown();
        this._pause();
        this._log('session_terminated', {cause: type});

        // Stop watching before the final overlay: stop() clears any overlay
        // still on screen, and the terminal one must survive it.
        this.stop();

        var reason = this._text('violation:' + type);
        this._notify(reason);
        this._showOverlay(this._text('terminated:title'), reason,
            this._text('terminated:close'), function() {
                self.onTerminate({type: type, closed: true});
            }, true);

        // Tell the caller immediately so the server-side end is recorded
        // without waiting for the learner to click anything.
        this.onTerminate({type: type, closed: false});
    };

    /* ---------- OS notification ---------- */

    AttentionMonitor.prototype.requestNotificationPermission = function() {
        if (!('Notification' in window)) {
            return Promise.resolve(false);
        }
        if (window.Notification.permission === 'granted') {
            return Promise.resolve(true);
        }
        if (window.Notification.permission === 'denied') {
            return Promise.resolve(false);
        }
        return window.Notification.requestPermission().then(function(result) {
            return result === 'granted';
        }).catch(function() {
            return false;
        });
    };

    AttentionMonitor.prototype._notify = function(body) {
        if (!this.desktopNotification || !('Notification' in window)) {
            return;
        }
        if (window.Notification.permission !== 'granted') {
            return;
        }
        try {
            var notification = new window.Notification(this._text('notification:title'), {
                body: body,
                requireInteraction: true,
                tag: 'proctor'
            });
            notification.onclick = function() {
                window.focus();
                notification.close();
            };
        } catch (error) {
            // The in-page overlay already carries the message.
            return;
        }
    };

    /* ---------- ticks ---------- */

    AttentionMonitor.prototype._tick = function() {
        if (this._terminated) {
            return;
        }
        var now = Date.now();

        // Random clips keep running even while the video is paused — who is
        // sitting there matters most when the lesson is not playing.
        if (this.clipsPerHour > 0 && now >= this._nextClipAt) {
            this._recordRandomClip(now);
        }

        // A paused lesson is one the learner stopped on purpose; there is no
        // reason to police attention to something that is not playing. An
        // exam has no lesson, so _underway() is true throughout.
        if (!this._underway() && !this._confirmPending) {
            return;
        }

        if (this.clickConfirmMs > 0 && !this._confirmPending &&
                now - this._lastConfirm >= this.clickConfirmMs) {
            this._askConfirm(now);
        }

        if (this._confirmPending && now > this._confirmDeadline) {
            this._confirmPending = false;
            this._lastConfirm = now;
            this._interrupt('click_confirm_timeout');
        }

        if (this.mouseIdleMs > 0) {
            var idleRemainMs = this.mouseIdleMs - (now - this._lastActivity);
            if (idleRemainMs <= 0) {
                this._lastActivity = now;
                this._hideCountdown();
                this._interrupt('mouse_idle');
            } else if (this.mouseIdleWarnMs > 0 && idleRemainMs <= this.mouseIdleWarnMs) {
                this._showCountdown('idle', Math.ceil(idleRemainMs / 1000));
            } else if (this._countdownType === 'idle') {
                this._hideCountdown();
            }
        }

        if (this.presenceMs > 0 && this.getSnapshot &&
                now - this._lastPresence >= this.presenceMs) {
            this._lastPresence = now;
            this._checkPresence();
        }

        if (this.identityEnabled && this.verifyMs > 0 && this.getSnapshot &&
                now - this._lastVerify >= this.verifyMs) {
            this._lastVerify = now;
            this._checkIdentity();
        }
    };

    AttentionMonitor.prototype._askConfirm = function(now) {
        var self = this;
        this._confirmPending = true;
        this._confirmDeadline = now + this.clickConfirmGraceMs;

        this._showOverlay(this._text('confirm:title'), this._text('confirm:body'),
            this._text('confirm:button'), function() {
                self._confirmPending = false;
                self._lastConfirm = Date.now();
                self._removeOverlay();
                self._log('click_confirm_ok', {});
                self._play();
            }, false);
    };

    /* ---------- face checks ---------- */

    AttentionMonitor.prototype._checkPresence = function() {
        var self = this;
        if (this._presenceGracing) {
            // Already chasing down the last bad frame at its own pace;
            // the periodic schedule does not need to pile on another check.
            return;
        }
        this.getSnapshot().then(function(blob) {
            return self.api.analyze(blob);
        }).then(function(response) {
            if (!response.ok) {
                // A check that could not run is not a check that passed. It
                // was logged as presence_ok once, and a dead face service
                // looked like a room full of attentive learners.
                self._log('presence_error', {code: response.errorcode});
            } else if (response.present === false) {
                self._beginPresenceLoss(response.reason || 'no_face');
            } else if (response.warning === 'multiple_faces') {
                self._beginPresenceLoss('multiple_faces');
            } else {
                self._log('presence_ok', {});
            }
            return response;
        }).catch(function(error) {
            self._log('presence_error', {message: String(error)});
        });
    };

    /**
     * One bad frame is not proof nobody is there — a hand passing in front of
     * the lens looks the same as an empty chair for the instant it takes.
     * With no grace configured this reproduces the old behaviour exactly:
     * pause on the first bad frame, which is what a test that leaves
     * presenceWarnSec unset is relying on.
     *
     * @param {String} reason what the first bad frame reported
     */
    AttentionMonitor.prototype._beginPresenceLoss = function(reason) {
        if (this.presenceWarnMs <= 0) {
            this._interrupt('face_absent', {reason: reason});
            return;
        }
        this._startPresenceGrace(reason);
    };

    /**
     * Keep re-checking for the length of the grace window, showing the
     * learner how long is left, instead of pausing on the frame that started
     * it. Runs on its own clock rather than folding into _tick's one-second
     * schedule, so the countdown shown is the countdown acted on.
     *
     * @param {String} reason
     */
    AttentionMonitor.prototype._startPresenceGrace = function(reason) {
        var self = this;
        if (this._presenceGracing) {
            return;
        }
        this._presenceGracing = true;
        this._log('presence_lost', {reason: reason});
        var deadline = Date.now() + this.presenceWarnMs;

        var poll = function() {
            if (self._terminated || !self._presenceGracing) {
                return;
            }
            var remainMs = deadline - Date.now();
            if (remainMs <= 0) {
                self._presenceGracing = false;
                self._hideCountdown();
                self._interrupt('face_absent', {reason: reason});
                return;
            }
            self._showCountdown('presence', Math.ceil(remainMs / 1000));

            if (!self.getSnapshot) {
                setTimeout(poll, 1000);
                return;
            }
            self.getSnapshot().then(function(blob) {
                return self.api.analyze(blob);
            }).then(function(response) {
                if (!self._presenceGracing) {
                    return;
                }
                if (response.ok && response.present !== false &&
                        response.warning !== 'multiple_faces') {
                    self._presenceGracing = false;
                    self._hideCountdown();
                    self._log('presence_restored', {});
                    return;
                }
                setTimeout(poll, 1500);
            }).catch(function() {
                setTimeout(poll, 1500);
            });
        };
        poll();
    };

    AttentionMonitor.prototype._checkIdentity = function() {
        var self = this;
        this.getSnapshot().then(function(blob) {
            return self.api.verify(blob, self.storeSnapshots);
        }).then(function(response) {
            if (!response.ok) {
                self._log('verify_error', {code: response.errorcode});
                return response;
            }

            self._log('identity_check', {
                decision: response.decision,
                similarity: response.similarity,
                liveness: response.livenessscore
            });

            if (response.decision === 'fail' || response.decision === 'fail_liveness') {
                self._log('face_mismatch', {decision: response.decision});
                if (self.strictLockdown) {
                    self._terminate(response.decision);
                } else {
                    self._interrupt(response.decision);
                }
            } else if (response.decision === 'review') {
                self._interrupt('face_review');
            }
            return response;
        }).catch(function(error) {
            self._log('verify_error', {message: String(error)});
        });
    };

    /* ---------- random evidence clip ---------- */

    AttentionMonitor.prototype._scheduleNextClip = function(now) {
        if (!this.clipsPerHour || this.clipsPerHour <= 0) {
            this._nextClipAt = Infinity;
            return;
        }
        var mean = 3600000 / this.clipsPerHour;
        // Unpredictable spacing: 40%-160% of the mean interval.
        this._nextClipAt = now + mean * (0.4 + Math.random() * 1.2);
    };

    AttentionMonitor.prototype._recordRandomClip = function(now) {
        var self = this;
        this._scheduleNextClip(now);
        if (this._recording) {
            return;
        }
        var stream = this.getStream ? this.getStream() : null;
        if (!stream || typeof MediaRecorder === 'undefined') {
            this._log('clip_skipped', {reason: stream ? 'no_media_recorder' : 'no_stream'});
            return;
        }

        var recorder;
        try {
            var mime = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm']
                .find(function(candidate) {
                    return MediaRecorder.isTypeSupported(candidate);
                }) || '';
            recorder = new MediaRecorder(stream, mime ? {mimeType: mime} : undefined);
        } catch (error) {
            this._log('clip_error', {message: String(error)});
            return;
        }

        this._recording = true;
        this._recorder = recorder;
        var chunks = [];
        recorder.ondataavailable = function(event) {
            if (event.data && event.data.size) {
                chunks.push(event.data);
            }
        };
        recorder.onstop = function() {
            self._recording = false;
            self._recorder = null;
            self._uploadClip(new Blob(chunks, {type: recorder.mimeType || 'video/webm'}));
        };
        recorder.start();
        this._log('clip_started', {seconds: this.clipMs / 1000});
        this._clipTimer = setTimeout(function() {
            if (recorder.state !== 'inactive') {
                recorder.stop();
            }
        }, this.clipMs);
    };

    AttentionMonitor.prototype._uploadClip = function(blob) {
        var self = this;
        this.api.storeEvidence('clip', 'random_sample', blob)
            .then(function(response) {
                self._log(response.ok ? 'clip_uploaded' : 'clip_error',
                    response.ok ? {evidenceid: response.evidenceid} : {code: response.errorcode});
                return response;
            }).catch(function(error) {
                self._log('clip_error', {message: String(error)});
            });
    };

    /** Capture a still immediately when a violation happens. */
    AttentionMonitor.prototype._captureEvidence = function(reason) {
        var self = this;
        if (!this.getSnapshot) {
            return;
        }
        this.getSnapshot().then(function(blob) {
            return self.api.storeEvidence('snapshot', reason, blob);
        }).catch(function() {
            // Supplementary evidence — never let it break policy enforcement.
            return null;
        });
    };

    AttentionMonitor.prototype._stopRecording = function() {
        clearTimeout(this._clipTimer);
        if (this._recorder && this._recorder.state !== 'inactive') {
            try {
                this._recorder.stop();
            } catch (error) {
                // Already stopped.
            }
        }
    };

    /* ---------- interruption and overlay ---------- */

    AttentionMonitor.prototype._interrupt = function(type, detail) {
        var self = this;
        if (this._terminated) {
            return;
        }
        this._pause();
        this._log(type, detail || {});
        this._interruptOverlay(type, this._text('violation:' + type));
    };

    AttentionMonitor.prototype._interruptOverlay = function(type, message) {
        var self = this;
        this._showOverlay(this._text('paused:title'), message,
            this._text('paused:resume'), function() {
                self._removeOverlay();
                self._lastActivity = Date.now();
                self._lastConfirm = Date.now();
                self._log('resumed', {after: type});
                self._play();
            }, true);
    };

    /**
     * Where an overlay or a countdown goes.
     *
     * Over the lesson when there is one, and over the page when there is not.
     * The detached stand-in an exam used to be given had no parent at all, so
     * this read null and getComputedStyle threw — inside a promise, where it
     * surfaced as nothing. A learner whose exam was cut short was told by an
     * overlay that could not be built.
     *
     * @return {Object} the element to append to, and whether it is the page
     */
    AttentionMonitor.prototype._overlayHost = function() {
        var host = this.video && this.video.parentElement;
        if (!host) {
            return {element: document.body, standalone: true};
        }
        if (window.getComputedStyle(host).position === 'static') {
            host.style.position = 'relative';
        }
        return {element: host, standalone: false};
    };

    AttentionMonitor.prototype._showOverlay = function(title, message, buttonText, onClick, blocking) {
        this._removeOverlay();
        var host = this._overlayHost();

        var overlay = document.createElement('div');
        overlay.className = 'proctor-overlay'
            + (blocking ? ' proctor-overlay-blocking' : '')
            + (host.standalone ? ' proctor-overlay-standalone' : '');
        overlay.dataset.blocking = blocking ? 'true' : 'false';

        var titleEl = document.createElement('div');
        titleEl.className = 'proctor-overlay-title';
        titleEl.textContent = title;

        var messageEl = document.createElement('div');
        messageEl.className = 'proctor-overlay-message';
        messageEl.textContent = message;

        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-primary proctor-overlay-btn';
        button.textContent = buttonText;
        button.addEventListener('click', onClick);

        overlay.appendChild(titleEl);
        overlay.appendChild(messageEl);
        overlay.appendChild(button);
        host.element.appendChild(overlay);
        this._overlay = overlay;
    };

    AttentionMonitor.prototype._removeOverlay = function() {
        if (this._overlay) {
            this._overlay.remove();
            this._overlay = null;
        }
    };

    /**
     * A small non-blocking badge counting down to a pause that has not
     * happened yet — separate from _showOverlay's full-screen blocking one,
     * which only appears once the video has actually been paused.
     *
     * @param {String} type 'idle' or 'presence', which string to show
     * @param {Number} seconds whole seconds left
     */
    AttentionMonitor.prototype._showCountdown = function(type, seconds) {
        this._countdownType = type;
        if (!this._countdownEl) {
            var host = this._overlayHost();
            var el = document.createElement('div');
            el.className = 'proctor-countdown'
                + (host.standalone ? ' proctor-countdown-standalone' : '');
            host.element.appendChild(el);
            this._countdownEl = el;
        }
        this._countdownEl.textContent = this._text('countdown:' + type, seconds);
    };

    AttentionMonitor.prototype._hideCountdown = function() {
        this._countdownType = null;
        if (this._countdownEl) {
            this._countdownEl.remove();
            this._countdownEl = null;
        }
    };

    /**
     * One piece of user-facing text.
     *
     * Falls back to the key itself rather than to an empty string. An overlay
     * with no words on it looks like a broken page; an overlay reading
     * "violation:mouse_idle" looks like a missing translation, which is what
     * it is, and says which key to add.
     *
     * @param {String} key
     * @param {Number|String} [param] substituted for {$a}
     * @return {String}
     */
    AttentionMonitor.prototype._text = function(key, param) {
        var text = this.strings[key];
        if (text === undefined) {
            return key;
        }
        return param === undefined
            ? text : String(text).replace('{$a}', param);
    };

    AttentionMonitor.prototype._log = function(type, detail) {
        var videotime = this.video ? Math.round(this.video.currentTime) : null;
        this.api.logEvent(type, detail, videotime).catch(function() {
            // Losing one audit line must not stop enforcement; the server-side
            // gap is itself visible in the log.
            return null;
        });
    };

    return AttentionMonitor;
}));
