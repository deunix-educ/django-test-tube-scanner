
    const cpu_used = sId('cpu-used');
    const shm_used = sId('shm-used');
    const mem_used = sId('mem-used');
    const disk_used = sId('disk-used');
    const ramdisk_used = sId('ramdisk-used');

    let autoTimer = null;

    async function fetchStats() {
        try {
            const r = await fetch(stats_endpoint, { credentials: 'same-origin' });
            if (!r.ok) throw new Error('HTTP ' + r.status);
            const j = await r.json();
            //console.log(j);
            const cpu_percent = j.cpu_info.cpu_percent+'%'; cpu_used.style.setProperty("--cpu-used", cpu_percent); cpu_used.title=`Cpu: ${cpu_percent}`;
            const shm_length = j.shm.length; shm_used.style.setProperty("--shm_used", shm_length);  shm_used.title= `Shm: ${shm_length}`;
            const virtual_memory = j.memory_info.virtual_memory.percent+'%'; mem_used.style.setProperty("--mem-used", virtual_memory); mem_used.title=`Mem: ${virtual_memory}`;
            const root_percent = j.disk_info.root.percent+'%'; disk_used.style.setProperty("--disk-used", root_percent); disk_used.title=`Disk: ${root_percent}`;
            let ramdisk_percent = "0%";
            if (! j.ramdisk_info)  ramdisk_percent = j.ramdisk_info.percent+'%';
            ramdisk_used.style.setProperty("--ramdisk-used", ramdisk_percent); ramdisk_used.title=`Ramdisk: ${ramdisk_percent}`;

        } catch (e) {
            console.log('Error: ' + e.message);
        }
    }
    function auto_fetch_start() { fetchStats(); autoTimer = setInterval(fetchStats, 5000);}
    function auto_fetch_stop()  { clearInterval(autoTimer);  autoTimer = null; }

    auto_fetch_start();
