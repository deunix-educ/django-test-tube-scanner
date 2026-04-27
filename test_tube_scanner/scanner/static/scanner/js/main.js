
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
        this.session = options.session; 
        this.scan_bt  = options.scan; 
        this.halt_bt    = options.halt; 
        this.debug   = options.debug; 
        this.median  = options.median; 
        this.crop    = options.crop; 
        this.speed_px_s   = options.speed_px_s; 
        this.axial_speed  = options.axial_speed; 
        this.axial_pos    = options.axial_pos; 
        this.area_px      = options.area_px; 
        this.frame_count  = options.frame_count; 
        this.scan_state   = options.scan_state;
    }

    init_controls() {
        this.median.addEventListener('click',(e) => { this._send({ type: 'calibrate', topic: "median" }); });
        this.crop.addEventListener('click',  (e) => { this._send({ type: 'calibrate', topic: "crop" }); });
        this.scan_bt.addEventListener('click',  (e) => { this.scan(); });
        this.halt_bt.addEventListener('click',  (e) => { this.halt(); });
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
            if (payload.scan_state)   { this.scan_state.textContent=payload.scan_state;}

            if (payload.detected && use_tracking) { 
                this.cx.textContent = payload.cx; this.cy.textContent = payload.cy;
                this.speed_px_s.textContent = payload.speed_px_s; 
                this.axial_speed.textContent = payload.axial_speed; 
                this.axial_pos.textContent = payload.axial_pos;
                this.area_px.textContent = payload.area_px; 
                this.frame_count.textContent = payload.count;           
            }              
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