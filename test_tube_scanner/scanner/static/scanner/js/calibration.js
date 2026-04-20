
class ScannerManager {

    constructor(container) {
        this.container = container;
        this.socket = null;
        this.axes = 0;
        this.cropping = 0;
        this.debug_count = 0
    }

    init_controls() {
        this.ts = sId("_ts");
        this.cx = sId("_cx");
        this.cy = sId("_cy");
        this.speed_px_s  = sId("_speed_px_s");
        this.axial_speed = sId("_axial_speed");
        this.axial_pos   = sId("_axial_pos");
        this.area_px     = sId("_area_px");
        this.frame_count = sId("_count");
        
        const goto_0  = sId("_goto-0");
        const goto_xy = sId("_goto-xy");
        const xy_base = sId("_xy-base");
        const xy_step  = sId("_xy-step");
        const up    = sId("_up");
        const down  = sId("_down");
        const left  = sId("_left");
        const right = sId("_right");
        this.duration = sId("_duration");
        this.feed   = sId("_feed");
        this.step   = sId("_step");
        this.well   = sId("_well");
        this.x      = sId("_x");
        this.y      = sId("_y");
        this.dx     = sId("_dx");
        this.dy     = sId("_dy");
        this.xbase  = sId("_xbase");
        this.ybase  = sId("_ybase");
        this.debug  = sId("_debug");
        this.well_btn = sId("_well_btn");  
        
        const test   = sId("_test");
        const halt   = sId("_halt");
        
        const calib_debug = sId("_calib_debug");
        const calib_center = sId("_calib_center");
        const previous = sId("_previous");        
        const next = sId("_next");        
        const set_well = sId("_set_well");  
             
        const median = sId("_median");
        const crop = sId("_crop");
        const crop_radius = sId("_crop_radius");
        

        up.addEventListener('mousedown',      (e) => { this._send({ type: 'calibrate', topic: "up" }); });
        down.addEventListener('mousedown',    (e) => { this._send({ type: 'calibrate', topic: "down" }); });
        left.addEventListener('mousedown',    (e) => { this._send({ type: 'calibrate', topic: "left" }); });
        right.addEventListener('mousedown',   (e) => { this._send({ type: 'calibrate', topic: "right" }); });

        goto_0.addEventListener('click',     (e) => { this.clear_buttons(); this._send({ type: 'calibrate', topic: "goto_0" }); });
        goto_xy.addEventListener('click',    (e) => { this.clear_buttons(); this._send({ type: 'calibrate', topic: "goto_xy" }); });
        xy_base.addEventListener('click',    (e) => { this._send({ type: 'calibrate', topic: "xy_base" }); });
        xy_step.addEventListener('click',    (e) => { this._send({ type: 'calibrate', topic: "xy_step" }); });
        
        calib_debug.addEventListener('click',(e) => { this._send({ type: 'calibrate', topic: "calib_debug" }); });       
        previous.addEventListener('click',    (e) => { this._send({ type: 'calibrate', topic: "previous" }); });
        next.addEventListener('click',    (e) => { this._send({ type: 'calibrate', topic: "next" }); });       
        set_well.addEventListener('click',(e) => { this._send({ type: 'calibrate', topic: "set_well" }); });       
        
        median.addEventListener('click',     (e) => { this._send({ type: 'calibrate', topic: "median" }); });
        crop.addEventListener('click',       (e) => { this._send({ type: 'calibrate', topic: "crop" }); });
        crop_radius.addEventListener('change',(e) => { this._send({ type: 'calibrate', topic: "crop_radius", value: crop_radius.value }); });
        this.well.addEventListener("change", (e) => { this._send({ type: 'calibrate', topic: "position", value: e.target.value }); });
        this.step.addEventListener("change", (e) => { this._send({ type: 'calibrate', topic: "step", value: e.target.value }); });
        this.feed.addEventListener("change", (e) => { this._send({ type: 'calibrate', topic: "feed", value: e.target.value }); });
        this.duration.addEventListener("change", (e) => { this._send({ type: 'calibrate', topic: "duration", value: e.target.value }); });
        
        this.dx.addEventListener("change", (e) => { this._send({ type: 'calibrate', topic: "dx", value: e.target.value }); });
        this.dy.addEventListener("change", (e) => { this._send({ type: 'calibrate', topic: "dy", value: e.target.value }); });

        test.addEventListener('click',  (e) => { this._send({ type: 'calibrate', topic: "test" }); });
        calib_center.addEventListener('click',  (e) => { this._send({ type: 'calibrate', topic: "center" }); });
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
            if (payload.xy)     { this.x.textContent=payload.x.toFixed(2); this.y.textContent=payload.y.toFixed(2); }
            if (payload.state)  { this.debug.insertAdjacentHTML('afterbegin', `<li>[ ${++this.debug_count} - ${payload.state} ]: ${payload.msg}</li>`); }
            if (payload.ts)     { this.ts.textContent = timestampToLocalISOString(payload.ts); }

            if (payload.detected && use_tracking) { 
                this.cx.textContent = payload.cx; this.cy.textContent = payload.cy;
                this.speed_px_s.textContent = payload.speed_px_s; 
                this.axial_speed.textContent = payload.axial_speed; 
                this.axial_pos.textContent = payload.axial_pos;
                this.area_px.textContent = payload.area_px; 
                this.frame_count.textContent = payload.count;           
            }
            if (payload.buttons) { this.well_btn.innerHTML = payload.buttons; }

        } catch(e) { console.log(e); }
    }
    
    clear_buttons() { document.querySelectorAll('button.w3-button.well').forEach(btn => {btn.classList.remove('w3-green'); }); }
    goto_well(b)    { this.clear_buttons(); b.classList.add('w3-green'); this._send({ type: 'calibrate', topic: "goto", value: b.value }); }
    init()          {
        this.axes = 0;
        this.cropping = 0;
        this.clear_buttons();
        this._send({
            type: 'calibrate',
            topic: "init",
            feed: this.feed.value,
            step: this.step.value,
            position: this.well.value,
            duration: this.duration.value
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