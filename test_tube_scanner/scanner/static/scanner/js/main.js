
class ScannerManager {

    constructor(container) {
        this.container = container;
        this.socket = null;
        this.axes = 0;
        this.cropping = 1;
        this.debug_count = 0
    }

    toggle_median() { this.axes = !this.axes; return this.axes; }
    toggle_crop()   { this.croping = !this.croping; return this.croping; }

    init_controls() {
        this.session= sId("_session");
        this.ts      = sId("_ts");
        this.x      = sId("_x");
        this.y      = sId("_y");
        this.debug  = sId("_debug");
        const scan  = sId("_scan");
        const halt   = sId("_halt");
        const median = sId("_median");
        const crop = sId("_crop");

        median.addEventListener('click',(e) => { this._send({ type: 'calibrate', topic: "median", value: this.toggle_median() }); });
        crop.addEventListener('click',  (e) => { this._send({ type: 'calibrate', topic: "crop", value: this.toggle_crop() }); });
        scan.addEventListener('click',  (e) => { this.scan(); });
        halt.addEventListener('click',  (e) => { this.halt(); });
    }

    registerSocket(socket)  {
        this.socket = socket;
        this.init_controls();
    }

    update(payload) {
        try {
            if (payload.jpeg)   { this.container.src = `data:image/jpeg;base64,${payload.jpeg}`; }
            if (payload.xy)     { this.x.textContent=payload.x.toFixed(2); this.y.textContent=payload.y.toFixed(2); }
            if (payload.state)  { this.debug.insertAdjacentHTML('afterbegin', `<li>[ ${++this.debug_count} - ${payload.state} ]: ${payload.msg}</li>`); }
            if (payload.ts)     { this.ts.textContent = timestampToLocalISOString(payload.ts); }
        } catch(e) { console.log(e); }
    }

    init()          { this.axes = 0;  this.cropping = 1; this._send({ type: 'scanner', topic: "init", });  }
    scan()          { this._send({ type: 'scanner', topic: "scan", session: this.session.value ? this.session.value: "0" }); }
    halt()          { this._send({ type: 'calibrate', topic: "halt" }); }

    _send(message)  { this.socket.send(message); }
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