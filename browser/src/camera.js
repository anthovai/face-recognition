// Camera access and frame capture, shared by the enrolment and lesson pages.
//
// The preview is mirrored in CSS so it feels like a mirror, but snapshots are
// drawn straight from the video element and are therefore NOT mirrored. That
// distinction matters: active_liveness maps yaw signs against the raw frame,
// so mirroring the capture would invert "turn left" and "turn right".
(function (root, factory) {
    if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else if (typeof define === 'function' && define.amd) {
        define([], factory);
    } else {
        root.Proctor = root.Proctor || {};
        root.Proctor.Camera = factory();
    }
}(typeof self !== 'undefined' ? self : this, function () {


    var Camera = function(videoElement) {
        this.video = videoElement;
        this.stream = null;
        this.canvas = document.createElement('canvas');
    };

    /**
     * One word for why the camera did not start.
     *
     * @param {Error} error whatever getUserMedia rejected with
     * @return {String} denied | busy | nocamera | generic
     */
    Camera.reason = function(error) {
        var name = (error && error.name) || '';
        if (name === 'NotAllowedError' || name === 'PermissionDeniedError'
                || name === 'SecurityError') {
            return 'denied';
        }
        if (name === 'NotReadableError' || name === 'TrackStartError'
                || name === 'AbortError') {
            return 'busy';
        }
        if (name === 'NotFoundError' || name === 'DevicesNotFoundError'
                || name === 'OverconstrainedError') {
            return 'nocamera';
        }
        return 'generic';
    };

    /**
     * Ask for the camera and start the preview.
     *
     * @return {Promise<MediaStream>}
     */
    Camera.prototype.start = function() {
        var self = this;
        if (this.stream) {
            return Promise.resolve(this.stream);
        }
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            return Promise.reject(new Error('nocamera'));
        }
        return navigator.mediaDevices.getUserMedia({
            video: {width: {ideal: 1280}, height: {ideal: 720}, facingMode: 'user'},
            audio: false
        }).then(function(stream) {
            self.stream = stream;
            self.video.srcObject = stream;
            return self.video.play().then(function() {
                return stream;
            });
        }).catch(function(error) {
            // Named, because the fixes are different people's jobs. "Denied"
            // is the learner's own permission prompt; "busy" is another
            // program holding the camera; "none" is hardware. One generic
            // message for all three sends every case to the help desk — the
            // same mistake the face service made when it blamed the lighting
            // for a low detection score.
            throw new Error(Camera.reason(error));
        });
    };

    Camera.prototype.stop = function() {
        if (this.stream) {
            this.stream.getTracks().forEach(function(track) {
                track.stop();
            });
            this.stream = null;
        }
        this.video.srcObject = null;
    };

    Camera.prototype.getStream = function() {
        return this.stream;
    };

    /**
     * Grab the current frame as a JPEG blob.
     *
     * @param {Number} [quality]
     * @return {Promise<Blob>}
     */
    Camera.prototype.snapshot = function(quality) {
        var self = this;
        return new Promise(function(resolve, reject) {
            var width = self.video.videoWidth;
            var height = self.video.videoHeight;
            if (!width || !height) {
                reject(new Error('novideo'));
                return;
            }
            self.canvas.width = width;
            self.canvas.height = height;
            self.canvas.getContext('2d').drawImage(self.video, 0, 0, width, height);
            self.canvas.toBlob(function(blob) {
                if (blob) {
                    resolve(blob);
                } else {
                    reject(new Error('nosnapshot'));
                }
            }, 'image/jpeg', quality === undefined ? 0.9 : quality);
        });
    };

    return Camera;
}));
