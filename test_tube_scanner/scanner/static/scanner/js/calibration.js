
class ScannerManager {

    constructor(container, options = {}) {
        this.container = container;
        this.socket = null;
        this.debug_count = 0;
        
        this.ts = options.ts; 
        this.cx = options.cx; 
        this.cy = options.cy; 
        this.x  = options.x; 
        this.y  = options.y;        
        this.xbase= options.xbase; 
        this.ybase= options.ybase; 
        this.test = options.test; 
        this.halt = options.halt;      
        this.speed_px_s  = options.speed_px_s; 
        this.axial_speed = options.axial_speed; 
        this.axial_pos   = options.axial_pos; 
        this.area_px     = options.area_px; 
        this.frame_count = options.frame_count; 
        this.goto_0  = options.goto_0; 
        this.goto_xy = options.goto_xy; 
        this.xy_base = options.xy_base; 
        this.up      = options.up; 
        this.down    = options.down; 
        this.left    = options.left; 
        this.right   = options.right; 
        this.duration= options.duration; 
        this.feed    = options.feed; 
        this.step    = options.step; 
        this.well    = options.well; 
        this.debug   = options.debug; 
        this.calib_debug = options.calib_debug; 
        this.calib_center= options.calib_center; 
        this.previous    = options.previous;   
        this.next        = options.next;     
        this.set_well    = options.set_well; 
        this.well_btn    = options.well_btn;  
        this.median      = options.median; 
        this.crop        = options.crop; 
        this.crop_radius = options.crop_radius;
        this.calib_auto  = options.calib_auto;
    }
    
    init_controls() {       
        this.up.addEventListener('mousedown',      (e) => { this._send({ type: 'calibrate', topic: "up" }); });
        this.down.addEventListener('mousedown',    (e) => { this._send({ type: 'calibrate', topic: "down" }); });
        this.left.addEventListener('mousedown',    (e) => { this._send({ type: 'calibrate', topic: "left" }); });
        this.right.addEventListener('mousedown',   (e) => { this._send({ type: 'calibrate', topic: "right" }); });

        this.goto_0.addEventListener('click',      (e) => { this.clear_buttons(); this._send({ type: 'calibrate', topic: "goto_0" }); });
        this.goto_xy.addEventListener('click',     (e) => { this.clear_buttons(); this._send({ type: 'calibrate', topic: "goto_xy" }); });
        this.xy_base.addEventListener('click',     (e) => { this._send({ type: 'calibrate', topic: "xy_base" }); });
        
        this.calib_debug.addEventListener('click', (e) => { this._send({ type: 'calibrate', topic: "calib_debug" }); });       
        this.previous.addEventListener('click',    (e) => { this._send({ type: 'calibrate', topic: "previous" }); });
        this.next.addEventListener('click',        (e) => { this._send({ type: 'calibrate', topic: "next" }); });       
        this.set_well.addEventListener('click',    (e) => { this._send({ type: 'calibrate', topic: "set_well" }); });       
        
        this.median.addEventListener('click',      (e) => { this._send({ type: 'calibrate', topic: "median" }); });
        this.crop.addEventListener('click',        (e) => { this._send({ type: 'calibrate', topic: "crop" }); });
        this.crop_radius.addEventListener('change',(e) => { this._send({ type: 'calibrate', topic: "crop_radius", value: this.crop_radius.value }); });
        this.well.addEventListener("change",       (e) => { this._send({ type: 'calibrate', topic: "position", value: e.target.value }); });
        this.step.addEventListener("change",       (e) => { this._send({ type: 'calibrate', topic: "step", value: e.target.value }); });
        this.feed.addEventListener("change",       (e) => { this._send({ type: 'calibrate', topic: "feed", value: e.target.value }); });
        this.duration.addEventListener("change",   (e) => { this._send({ type: 'calibrate', topic: "duration", value: e.target.value }); });

        this.test.addEventListener('click',         (e) => { this._send({ type: 'calibrate', topic: "test" }); });
        this.calib_center.addEventListener('click', (e) => { this._send({ type: 'calibrate', topic: "center" }); });
        this.calib_auto.addEventListener('click',   (e) => { this._send({ type: 'calibrate', topic: "auto" }); });
        this.halt.addEventListener('click',         (e) => { this._send({ type: 'calibrate', topic: "halt" }); });
    }

    registerSocket(socket)  {
        this.socket = socket;
        this.init_controls();
    }

    update(payload) {
        try {            
            if (payload.jpeg)   { this.container.src = `data:image/jpeg;base64,${payload.jpeg}`; }
            if (payload.xbase)  { this.xbase.textContent = payload.xbase;  this.ybase.textContent = payload.ybase; }
            if (payload.xy)     { this.x.textContent=payload.x.toFixed(2); this.y.textContent=payload.y.toFixed(2); }
            if (payload.state)  { this.debug.insertAdjacentHTML('afterbegin', `<li>[ ${++this.debug_count} - ${payload.state} ]: ${payload.msg}</li>`); }
            if (payload.ts)     { this.ts.textContent = timestampToLocalISOString(payload.ts); }

            /*
            if (payload.detected && use_tracking) { 
                this.cx.textContent = payload.cx; this.cy.textContent = payload.cy;
                this.speed_px_s.textContent = payload.speed_px_s; 
                this.axial_speed.textContent = payload.axial_speed; 
                this.axial_pos.textContent = payload.axial_pos;
                this.area_px.textContent = payload.area_px; 
                this.frame_count.textContent = payload.count;           
            }*/
            
            if (payload.buttons) { this.well_btn.innerHTML = payload.buttons; }
            if (payload.current >= 0) {                 
                document.querySelectorAll('button.w3-button.well').forEach(btn => {
                    if (btn.value==payload.current) { btn.classList.add('w3-green'); return; }
                    btn.classList.remove('w3-green'); 
                });
             }

        } catch(e) { console.log(e); }
    }
    
    clear_buttons() { document.querySelectorAll('button.w3-button.well').forEach(btn => {btn.classList.remove('w3-green'); }); }
    goto_well(b)    { this.clear_buttons(); b.classList.add('w3-green'); this._send({ type: 'calibrate', topic: "goto", value: b.value }); }
    init()          {
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