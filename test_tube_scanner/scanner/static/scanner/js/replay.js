
class ReplayProgressBar {
    constructor(parent, input) {
        this.input = input;
        this.parent = parent;
        this.isUserSeeking = false;

        input.addEventListener("input", () => {
            this.isUserSeeking = true;
            const percent = input.value / 1000;
            this.parent.seek(percent);
        });
        input.addEventListener("change", () => {
            this.isUserSeeking = false;
        });
    }
    update(progress) {
        if (this.isUserSeeking) return;
        this.input.value = progress * 1000;
    }
}

class ReplaySpeedControl {
    constructor(parent,  initialSpeed = 1) {
        this.parent = parent;

        this.SPEED_STEPS = [0.25, 0.5, 0.75, 1, 2, 4, 8, 16, 32];
        const initialIndex = this.SPEED_STEPS.indexOf(initialSpeed) !== -1
            ? this.SPEED_STEPS.indexOf(initialSpeed)
            : this.SPEED_STEPS.indexOf(1);

        this.parent.speed_control.addEventListener("input", () => {
            this.parent.speed_label.textContent = this.SPEED_STEPS[this.parent.speed_control.value];
        });

        this.parent.speed_control.addEventListener("change", () => {
            const speed = this.getSpeed();
            this.parent.setSpeed(speed);
        });
    }
    getSpeed() {
        return this.SPEED_STEPS[this.parent.speed_control.value];
    }
    updateSpeed(speed) {
         this.parent.speed_control.value = this.SPEED_STEPS.indexOf(speed);
         this.parent.speed_label.textContent = this.SPEED_STEPS[this.parent.speed_control.value];
    }
}

class ReplayManager {

    constructor(options = {}) {
        this.img    = options.img;
        this.btplay = options.play;
        this.btpause= options.pause;
        this.btstop = options.stop;
        this.ts     = options.ts;
        this.btsnapshot  = options.snapshot;
        this.btvideosnap = options.videosnap;
       
        this.speed_label   = options.speed_label;
        this.speed_control = options.speed_control;
        this.ts_iso   = options.ts_iso;
        this.percent  = options.percent;
        this.dt_left  = options.dt_left;
        this.dt_right = options.dt_right;
        this.timeline = options.timeline;

        this.uuid  = options.uuid;
        this.fps   = options.fps;
        this.video_endpoint = options.video_endpoint;

        this.dt_start   = options.dt_start;
        this.dt_stop    = options.dt_stop;
        this.video_type = options.video_type || 'mp4';
        this.state  = null;
        this.socket = null;
        this.cursor = null;
    }

    registerSocket(socket)  {
        this.socket = socket;
    }

    async start() {
        if (!this.uuid) return;
        this.btplay.addEventListener('click',  (e) => { this.play(); });
        this.btpause.addEventListener('click', (e) => { this.pause(); });
        this.btstop.addEventListener('click',  (e) => { this.stop(); });
        this.btsnapshot.addEventListener('click',  (e) => { this.snapshot(); });
        this.btvideosnap.addEventListener('click', (e) => { this.videosnap(); });

        this.speedControl = new ReplaySpeedControl(this);
        this.progressBar = new ReplayProgressBar(this, this.timeline);

        this._update_container(this.dt_start);
        this.updateState("stopped");
    }

    updateProgessBar(progress) {
        if (this.progressBar) {
            this.progressBar.update(progress);
        }
    }

    updateState(state) {
        const rules = {
            stopped: { play: true,  pause: false, stop: false, range: true, snapshot: true, videosnap: true },
            playing: { play: false, pause: true,  stop: true, range: false , snapshot: false, videosnap: false },
            paused:  { play: true,  pause: false, stop: true, range: true , snapshot: true, videosnap: true }
        };
        const rule = rules[state];
        this.btplay.disabled  = !rule.play;
        this.btpause.disabled = !rule.pause;
        this.btstop.disabled  = !rule.stop;
        this.btsnapshot.disabled  = !rule.snapshot;
        this.btvideosnap.disabled = !rule.videosnap;
        this.timeline.disabled  = rule.range;
    }

    _setState(state) {
        this.state = state;
        this.updateState(state);
    }

    _update_container(cursor) {
        this.cursor = cursor;
        this.filter = {
           uuid: this.uuid,
           dt_start: cursor,
           dt_stop: this.dt_stop,
           fps: this.fps,
           speed: this.speedControl.getSpeed()
        }
        this.percent.textContent = '';
        this.updateProgessBar(0.0);
        const dt = cursor / 1_000;
        this.ts_iso.textContent = toLocalISOString(new Date(dt));
        this.dt_left.textContent = timestampToLocalISOString(dt/1_000);
        this.dt_right.textContent = timestampToLocalISOString(this.dt_stop/1_000_000);
        this._setState("stopped");
  }

   _update_content_slider(ts, progress) {
       this.cursor = ts;
       this.ts_iso.textContent = toLocalISOString(new Date(ts/1000));
       const percent = Math.ceil(progress * 1000000) / 10000;
       this.percent.textContent = percent.toFixed(3) +' %';
       this.updateProgessBar(progress);
   }

   update(payload) {
        try {
            if (payload.jpeg)   { this.img.src = `data:image/jpeg;base64,${payload.jpeg}`;   }
            if (payload.ts)     { this._update_content_slider(payload.ts, payload.progress); }
            if (payload.motif === "video-reset") { this._update_container(payload.dt_start); }
        } catch(e) { console.log(e); }
    }

    init()          { this._send({ type: 'replay', action: "init", });  }
    play()          { if (this.state === "playing") return; this._setState("playing"); this._send({ type: 'replay', action: "play", });  }
    pause()         { if (this.state !== "playing") return; this._setState("paused");  this._send({ type: 'replay', action: "pause", }); }
    stop()          { this._setState("stopped"); this._send({ type: 'replay', action: "stop", });  }

    setSpeed(speed) { this._send({ type: 'replay', action: "speed", value: speed }); }
    seek(percent)   { this._send({ type: 'replay', action: "seek",  value: percent });  }

    videosnap()     {
        let filename = `${this.uuid}-${this.ts_iso.textContent}.${this.video_type}`;
        filename = filename.replace(/ /g, '_');
        const ok = confirm(`Télécharger le fichier ?\n\n${filename}`);
        if (!ok) return false;

        fetch(this.video_endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'download',
                uuid: this.uuid,
                dt_start: this.cursor,
                dt_stop: this.dt_stop,
                fps: this.fps
            })
        }).then(res => {
            if (!res.ok) throw new Error(res.status);
            return res.blob();
        }).then(blob => {
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
        }).catch(error => {
            console.error('Erreur:', error);
        });

    }

    snapshot()      {
        let filename = `${this.uuid}-${this.ts_iso.textContent}.jpg`;
        filename = filename.replace(/ /g, '_');
        const ok = confirm(`Télécharger le fichier ?\n\n${filename}`);
        if (!ok) return false;

        const a = document.createElement('a');
        a.href = this.img.src;
        a.download = filename || 'image';
        document.body.appendChild(a);
        a.click();
        a.remove();
    }

    _send(message)  { 
        if (!this.uuid) return;
        this.socket.send({ ...message, ...this.filter }); 
    }
}

class MetadataSocket {
    constructor(url) {
        this.url = url;
        this.ws = null;
        this.manager = null;
        this.reconnectDelay = 1000;
        this.shouldReconnect = true;
        this.reconnect = false;
    }

    setManager(manager) { this.manager = manager; }

    connect()           {
        this.ws = new WebSocket(this.url);

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.manager.update(data);
        };

        this.ws.onopen = (event) => {
            if (this.manager && !this.reconnect)
                this.manager['init']();
            this.reconnect = false;
        };

        this.ws.onclose = () => {
            console.warn(`WebSocket closed...`);
            if (this.shouldReconnect) {
                this.reconnect = true;
                setTimeout(() => {
                    console.log("Reconnect WebSocket...");
                    this.connect();
                }, this.reconnectDelay);
            }
        };
    }
    send(obj) { if (this.ws?.readyState === WebSocket.OPEN) { this.ws.send(JSON.stringify(obj));  } }
}

