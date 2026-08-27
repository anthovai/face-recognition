// Lockdown — closes the browser-level exits during a monitored session.
//
// Ported from face-re/app/static/lockdown.js, behaviour unchanged. What
// changed: violation types now match the names log_event accepts, so they land
// in the same audit trail as the attention signals instead of a parallel one.
//
// Known limit, and it must be stated to customers rather than papered over:
// a web page has no operating-system privileges. Alt+Tab, the Windows key, a
// second monitor and a phone on the desk cannot be prevented. What this does
// is detect and report; ending the session on detection is AttentionMonitor's
// job. Real machine-level lockdown needs Safe Exam Browser or a kiosk app.
(function (root, factory) {
    if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else if (typeof define === 'function' && define.amd) {
        define([], factory);
    } else {
        root.Proctor = root.Proctor || {};
        root.Proctor.Lockdown = factory();
    }
}(typeof self !== 'undefined' ? self : this, function () {


    var Lockdown = function(opts) {
        opts = opts || {};
        this.root = opts.root || document.documentElement;
        this.onViolation = opts.onViolation || function() {};
        this.requireFullscreen = opts.requireFullscreen !== false;
        this.blockKeys = opts.blockKeys !== false;
        this.blockContextMenu = opts.blockContextMenu !== false;
        this.blockCopy = opts.blockCopy !== false;
        this.warnOnUnload = opts.warnOnUnload !== false;
        this.detectDevtools = opts.detectDevtools !== false;
        this._active = false;
        this._handlers = [];
        this._devtoolsSeen = false;
    };

    /* ---------- lifecycle ---------- */

    /**
     * Start locking down. Must be called from a user gesture, otherwise the
     * fullscreen request is refused by the browser.
     *
     * @return {Promise}
     */
    Lockdown.prototype.start = function() {
        var self = this;
        if (this._active) {
            return Promise.resolve();
        }
        this._active = true;

        if (this.blockContextMenu) {
            this._on(document, 'contextmenu', function(e) {
                e.preventDefault();
                self.onViolation('context_menu', {});
            });
        }

        if (this.blockCopy) {
            ['copy', 'cut', 'paste'].forEach(function(name) {
                self._on(document, name, function(e) {
                    e.preventDefault();
                    self.onViolation(name === 'paste' ? 'paste_attempt' : 'copy_attempt',
                        {action: name});
                });
            });
            this._on(document, 'selectstart', function(e) {
                e.preventDefault();
            });
            this._on(document, 'dragstart', function(e) {
                e.preventDefault();
            });
            this.root.style.userSelect = 'none';
        }

        if (this.blockKeys) {
            this._on(document, 'keydown', function(e) {
                self._onKeydown(e);
            }, true);
        }

        if (this.warnOnUnload) {
            this._beforeUnload = function(e) {
                e.preventDefault();
                e.returnValue = '';
                return '';
            };
            window.addEventListener('beforeunload', this._beforeUnload);
        }

        if (this.detectDevtools) {
            this._startDevtoolsWatch();
        }

        if (!this.requireFullscreen) {
            return Promise.resolve();
        }
        return this.enterFullscreen().then(function() {
            self._on(document, 'fullscreenchange', function() {
                if (!document.fullscreenElement && self._active) {
                    self.onViolation('fullscreen_exit', {});
                }
            });
        });
    };

    Lockdown.prototype.stop = function() {
        if (!this._active) {
            return;
        }
        this._active = false;
        this._handlers.forEach(function(entry) {
            entry[0].removeEventListener(entry[1], entry[2], entry[3]);
        });
        this._handlers = [];
        if (this._beforeUnload) {
            window.removeEventListener('beforeunload', this._beforeUnload);
            this._beforeUnload = null;
        }
        clearInterval(this._devtoolsTimer);
        this.root.style.userSelect = '';
        if (document.fullscreenElement) {
            document.exitFullscreen().catch(function() {
                return null;
            });
        }
    };

    /* ---------- fullscreen ---------- */

    Lockdown.prototype.enterFullscreen = function() {
        var self = this;
        if (document.fullscreenElement) {
            return Promise.resolve(true);
        }
        return this.root.requestFullscreen({navigationUI: 'hide'}).then(function() {
            return true;
        }).catch(function(error) {
            self.onViolation('fullscreen_denied', {message: String(error && error.message)});
            return false;
        });
    };

    /* ---------- keyboard ---------- */

    Lockdown.prototype._onKeydown = function(e) {
        var key = (e.key || '').toLowerCase();
        var ctrl = e.ctrlKey || e.metaKey;
        var blocked = null;

        if (key === 'f12') {
            blocked = 'devtools_suspected';
        } else if (ctrl && e.shiftKey && ['i', 'j', 'c'].indexOf(key) >= 0) {
            blocked = 'devtools_suspected';
        } else if (ctrl && ['t', 'n', 'w', 'p', 's', 'u', 'o'].indexOf(key) >= 0) {
            blocked = 'browser_shortcut';
        } else if (ctrl && key === 'tab') {
            blocked = 'tab_switch';
        } else if (e.altKey && key === 'tab') {
            blocked = 'app_switch';
        } else if (key === 'printscreen') {
            blocked = 'print_screen';
        }

        if (blocked) {
            e.preventDefault();
            e.stopPropagation();
            this.onViolation(blocked, {key: e.key});
        }
    };

    /* ---------- devtools heuristic ---------- */

    Lockdown.prototype._startDevtoolsWatch = function() {
        var self = this;
        // Docked devtools shrink the inner viewport well below the outer
        // window. Crude, and undockable devtools defeat it — it is a signal,
        // not a guarantee.
        this._devtoolsTimer = setInterval(function() {
            var gapWidth = window.outerWidth - window.innerWidth;
            var gapHeight = window.outerHeight - window.innerHeight;
            var open = gapWidth > 200 || gapHeight > 200;
            if (open && !self._devtoolsSeen) {
                self._devtoolsSeen = true;
                self.onViolation('devtools_suspected', {
                    gapwidth: gapWidth,
                    gapheight: gapHeight
                });
            } else if (!open) {
                self._devtoolsSeen = false;
            }
        }, 2000);
    };

    /* ---------- helper ---------- */

    Lockdown.prototype._on = function(target, name, fn, capture) {
        target.addEventListener(name, fn, capture || false);
        this._handlers.push([target, name, fn, capture || false]);
    };

    return Lockdown;
}));
