
class ScannerManager {

    constructor(container, multiwells=null) {
        this.container = container;
        this.socket = null;
        this.multiweels = multiwells;
        this.axes = 0;
        this.cropping = 0;
    }

    toggle_median() { this.axes = !this.axes; return this.axes; }
    toggle_crop()   { this.croping = !this.croping; return this.croping; }

    init_controls() {
        const goto_0  = sId("_goto-0");
        const goto_xy = sId("_goto-xy");
        const xy_base = sId("_xy-base");
        const xy_step  = sId("_xy-step");
        const up    = sId("_up");
        const down  = sId("_down");
        const left  = sId("_left");
        const right = sId("_right");
        this.feed   = sId("_feed");
        this.step   = sId("_step");
        this.well   = sId("_well");
        this.x      = sId("_x");
        this.y      = sId("_y");
        this.dx     = sId("_dx");
        this.dy     = sId("_dy");
        this.xbase  = sId("_xbase");
        this.ybase  = sId("_ybase");
        const test   = sId("_test");
        const halt   = sId("_halt");

        const median = sId("_median");
        const crop = sId("_crop");

        up.addEventListener('mousedown',      (e) => { this._send({ type: 'calibrate', topic: "up" }); });
        down.addEventListener('mousedown',    (e) => { this._send({ type: 'calibrate', topic: "down" }); });
        left.addEventListener('mousedown',    (e) => { this._send({ type: 'calibrate', topic: "left" }); });
        right.addEventListener('mousedown',   (e) => { this._send({ type: 'calibrate', topic: "right" }); });

        goto_0.addEventListener('click',     (e) => { this._send({ type: 'calibrate', topic: "goto_0" }); });
        goto_xy.addEventListener('click',    (e) => { this._send({ type: 'calibrate', topic: "goto_xy" }); });
        xy_base.addEventListener('click',    (e) => { this._send({ type: 'calibrate', topic: "xy_base" }); });
        xy_step.addEventListener('click',    (e) => { this._send({ type: 'calibrate', topic: "xy_step" }); });

        median.addEventListener('click',     (e) => { this._send({ type: 'calibrate', topic: "median", value: this.toggle_median() }); });
        crop.addEventListener('click',       (e) => { this._send({ type: 'calibrate', topic: "crop", value: this.toggle_crop() }); });
        this.well.addEventListener("change", (e) => { this._send({ type: 'calibrate', topic: "well", value: e.target.value }); });
        this.step.addEventListener("change", (e) => { this._send({ type: 'calibrate', topic: "step", value: e.target.value }); });
        this.feed.addEventListener("change", (e) => { this._send({ type: 'calibrate', topic: "feed", value: e.target.value }); });

        this.dx.addEventListener("change", (e) => { this._send({ type: 'calibrate', topic: "dx", value: e.target.value }); });
        this.dy.addEventListener("change", (e) => { this._send({ type: 'calibrate', topic: "dy", value: e.target.value }); });

        test.addEventListener('click',  (e) => { this._send({ type: 'calibrate', topic: "test" }); });
        halt.addEventListener('click',  (e) => { this._send({ type: 'calibrate', topic: "halt" }); });

    }

    registerSocket(socket)  {
        this.socket = socket;
        this.init_controls();
    }

    update(payload) {
        try {
            if (payload.jpeg)   { this.container.src = `data:image/jpeg;base64,${payload.jpeg}`; }
            if (payload.xbase)  { this.xbase.textContent = payload.xbase;  this.ybase.textContent = payload.ybase; }
            if (payload.dxy)    { this.dy.value=payload.dy; this.dx.value=payload.dx; }
            if (payload.xy)     { this.x.textContent=payload.x; this.y.textContent=payload.y; }
            //if (payload.ts)     { console.log(payload.ts); }
        } catch(e) { console.log(e); }
    }

    init()          {
        this._send({
            type: 'scanner',
            topic: "init",
            feed: this.feed.value,
            step: this.step.value,
            well: this.well.value
        });
    }
    start()         { this._send({ type: 'scanner', topic: "start"}); }
    halt()          { this._send({ type: 'scanner', topic: "halt" }); }

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