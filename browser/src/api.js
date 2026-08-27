// A reference implementation of the four calls AttentionMonitor makes.
//
// **This talks to YOUR backend, not to the face service.** That is the whole
// point of it being a separate file you are expected to adapt.
//
// The face service key must never reach a browser. Anyone holding it can ask
// "is this the same person" about any photograph they like, against any
// enrolled face — so the browser sends frames to an endpoint of yours, your
// server adds the key and forwards to the face service, and your server is
// also where the answer gets written down. That last part matters as much as
// the key: a decision recorded by the browser is a decision recorded by the
// party being watched.
//
// The four calls and what each must return:
//
//   analyze(blob)                  -> {ok, present, warning, reason, ...}
//        Proxy of the face service's POST /analyze. `present: false` and
//        `warning: 'multiple_faces'` are normal answers, not errors.
//
//   verify(blob, storeEvidence)    -> {ok, decision, similarity, errorcode}
//        Proxy of POST /verify, against the reference embedding your server
//        holds for whoever is signed in. `decision` is one of
//        pass | review | fail | fail_liveness.
//
//   storeEvidence(kind, reason, blob) -> {ok, evidenceid, errorcode}
//        Your own. `kind` is 'snapshot' or 'clip'. Nothing here reaches the
//        face service; this is your evidence store, under your retention
//        policy. Return {ok: false} rather than throwing if you would rather
//        drop it.
//
//   logEvent(type, detail, videotime) -> Promise
//        Your own audit trail. Called for every signal, including the
//        harmless ones. The resolved value is ignored; only rejection is
//        noticed, and even then only to be swallowed - losing one audit line
//        must never stop enforcement.
//
// Every call must return a Promise and must not throw synchronously.
(function (root, factory) {
    if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else if (typeof define === 'function' && define.amd) {
        define([], factory);
    } else {
        root.Proctor = root.Proctor || {};
        root.Proctor.createApi = factory();
    }
}(typeof self !== 'undefined' ? self : this, function () {

    /**
     * Read a Blob as base64, without the data: prefix.
     *
     * @param {Blob} blob
     * @return {Promise<String>}
     */
    var toBase64 = function (blob) {
        return new Promise(function (resolve, reject) {
            var reader = new FileReader();
            reader.onloadend = function () {
                var result = String(reader.result);
                var comma = result.indexOf(',');
                resolve(comma >= 0 ? result.slice(comma + 1) : result);
            };
            reader.onerror = reject;
            reader.readAsDataURL(blob);
        });
    };

    /**
     * @param {Object} opts
     * @param {String} opts.baseUrl where your own endpoints live, e.g. '/api/proctor'
     * @param {String} [opts.sessionId] passed through on every call, so your
     *        server can file everything against one sitting. Which sitting a
     *        frame belongs to is yours to decide and yours to trust; the
     *        browser is not in a position to be believed about it.
     * @param {Object} [opts.headers] added to every request — a CSRF token,
     *        a session cookie's companion header, whatever your stack needs.
     *        Do NOT put the face service key here.
     * @return {Object} the api object AttentionMonitor expects
     */
    return function createApi(opts) {
        var base = String(opts.baseUrl || '').replace(/\/+$/, '');
        var sessionId = opts.sessionId || '';
        var extraHeaders = opts.headers || {};

        var postJson = function (path, body) {
            var headers = {'Content-Type': 'application/json'};
            Object.keys(extraHeaders).forEach(function (name) {
                headers[name] = extraHeaders[name];
            });
            return fetch(base + path, {
                method: 'POST',
                credentials: 'same-origin',
                headers: headers,
                body: JSON.stringify(body)
            }).then(function (response) {
                // A non-200 is still an answer this module can act on, as long
                // as it is shaped like one. Rejecting instead would turn a
                // server error into an unhandled rejection at each call site.
                return response.json().catch(function () {
                    return {ok: false, errorcode: 'http_' + response.status};
                });
            });
        };

        return {
            analyze: function (blob) {
                return toBase64(blob).then(function (image) {
                    return postJson('/analyze', {
                        sessionid: sessionId,
                        image: image
                    });
                });
            },

            verify: function (blob, storeEvidence) {
                return toBase64(blob).then(function (image) {
                    return postJson('/verify', {
                        sessionid: sessionId,
                        image: image,
                        storeevidence: !!storeEvidence
                    });
                });
            },

            storeEvidence: function (kind, reason, blob) {
                return toBase64(blob).then(function (data) {
                    return postJson('/evidence', {
                        sessionid: sessionId,
                        kind: kind,
                        reason: reason,
                        data: data
                    });
                });
            },

            logEvent: function (type, detail, videotime) {
                return postJson('/event', {
                    sessionid: sessionId,
                    type: type,
                    detail: detail || {},
                    videotime: (videotime === null || videotime === undefined)
                        ? -1 : videotime
                });
            }
        };
    };
}));
