/*
** custom.js
** GNU GENERAL PUBLIC LICENSE: (c) DD miraceti.net return document.querySelectorAll(id);
*/
let s   = function(sel) 			{ return document.querySelector(sel);  };
let ss  = function(sel)             { return document.querySelectorAll(sel);  };
let sId = function(sel) 			{ return document.getElementById(sel); };
let isJsonObject  = function(value) { return value !== undefined && value !== null && typeof value === 'object'; }

let sidebarOpen   = function(width, left, right)	{ right.style.marginLeft=width; left.style.width=width; left.style.display="block"; };
let sidebarClose  = function(left, right) 			{ right.style.marginLeft="0"; left.style.display="none"; }
let sidebarAction = function(width, left, right) 	{ (left.style.display==="none") ? sidebarOpen(width, left, right): sidebarClose(left, right); };
let goFullscreen  = function()		{ if (!document.fullscreenElement) { document.documentElement.requestFullscreen(); } else { document.exitFullscreen(); } };

let uuidFromId    = function(id)	{ return id.getAttribute('id').split('-')[1]; }
let strReplace = function(str, c) 	{ return str.replace(/\s+g/, c); };
let rtrim = function(str, c) 		{ return str.replace(/\s+$/, c); };
let ltrim = function(str, c) 		{ return str.replace(/^\s+/, c); };
let lastString = function(str, c) 	{ let n = str.split(c);  return n[n.length - 1]; };

let toggleCheckboxesByName = function(name) {
    const boxes = document.querySelectorAll(`input[type="checkbox"][name="${name}"]`);
    const shouldCheck = Array.from(boxes).some(b => !b.checked);
    boxes.forEach(b => b.checked = shouldCheck);
};

let toggleDisplay = function(el) {
    const current = window.getComputedStyle(el).display;
    el.style.display = (current === 'none') ? 'block': 'none';
};

function toLocalISOString(date) {
    const offset = date.getTimezoneOffset() * 60000; // Convertir le décalage en millisecondes
    const localDate = new Date(date.getTime() - offset);
    return localDate.toISOString().slice(0, -1); // Retire le 'Z' final
}

function timestampToLocalISOString(timestamp) {
    const date = new Date(timestamp*1000);
    return toLocalISOString(date);
}

