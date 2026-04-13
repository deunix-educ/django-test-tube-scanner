class DualRangeSlider {
  constructor(root, options = {}) {
    // root: element containing the slider UI
    this.root = (typeof root === 'string') ? document.querySelector(root) : root;
    if (!this.root) throw new Error('Root element not found');

    // elements
    this.slider = this.root.querySelector('.slider');
    this.minRange = this.root.querySelector('.min-range');
    this.maxRange = this.root.querySelector('.max-range');
    this.minNumber = this.root.querySelector('.min-number');
    this.maxNumber = this.root.querySelector('.max-number');
    this.displayRange = this.root.querySelector('.display-range');
    this.highlight = this.root.querySelector('.range-highlight');

    // config
    this.min = Number(this.slider.dataset.min ?? this.minRange.min ?? 0);
    this.max = Number(this.slider.dataset.max ?? this.minRange.max ?? 100);
    this.gap = Number(options.gap ?? 0);

    this._bindEvents();
    this.updateFromInputs();
  }

  // calc & repaint
  updateHighlight() {
    const a = Number(this.minRange.value);
    const b = Number(this.maxRange.value);
    const pctA = (a - this.min) / (this.max - this.min) * 100;
    const pctB = (b - this.min) / (this.max - this.min) * 100;
    this.highlight.style.left = pctA + '%';
    this.highlight.style.width = (pctB - pctA) + '%';
  }

  // keep values coherent and sync UI
  updateFromInputs(triggerSource) {
    let a = Number(this.minRange.value);
    let b = Number(this.maxRange.value);

    if (a > b - this.gap) {
      if (triggerSource === 'min') a = b - this.gap;
      else if (triggerSource === 'max') b = a + this.gap;
      else a = Math.min(a, b - this.gap);
    }

    a = Math.max(this.min, Math.min(a, this.max));
    b = Math.max(this.min, Math.min(b, this.max));

    this.minRange.value = a;
    this.maxRange.value = b;
    this.minNumber.value = a;
    this.maxNumber.value = b;
    //if (this.displayRange) this.displayRange.textContent = a + ' — ' + b;
    if (this.displayRange)
        this.displayRange.innerHTML = `<div class="w3-row"><div class="w3-half">${a}</div><div class="w3-half w3-right-align">${b}</div></div>`;

    this.updateHighlight();
  }

  updateFromNumbers() {
    let a = Number(this.minNumber.value) || this.min;
    let b = Number(this.maxNumber.value) || this.max;
    if (a > b - this.gap) a = b - this.gap;
    a = Math.max(this.min, Math.min(a, this.max));
    b = Math.max(this.min, Math.min(b, this.max));
    this.minRange.value = a;
    this.maxRange.value = b;
    this.minNumber.value = a;
    this.maxNumber.value = b;
    //if (this.displayRange) this.displayRange.textContent = a + ' — ' + b;
    if (this.displayRange)
        this.displayRange.innerHTML = `<div class="w3-row"><div class="w3-half">${a}</div><div class="w3-half w3-right-align">${b}</div></div>`;
    this.updateHighlight();
  }

  _bindEvents() {
    this.minRange.addEventListener('input', () => this.updateFromInputs('min'));
    this.maxRange.addEventListener('input', () => this.updateFromInputs('max'));
    this.minNumber.addEventListener('change', () => this.updateFromNumbers());
    this.maxNumber.addEventListener('change', () => this.updateFromNumbers());

    // click on track reposition nearest thumb
    this.slider.addEventListener('click', (e) => {
      if (e.target.tagName.toLowerCase() === 'input') return;
      const rect = this.slider.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const pct = clickX / rect.width;
      const value = Math.round(pct * (this.max - this.min) + this.min);
      const distMin = Math.abs(value - Number(this.minRange.value));
      const distMax = Math.abs(value - Number(this.maxRange.value));
      if (distMin <= distMax) {
        this.minRange.value = Math.min(value, Number(this.maxRange.value));
      } else {
        this.maxRange.value = Math.max(value, Number(this.minRange.value));
      }
      this.updateFromInputs();
    });
  }

  // public API: get current values
  getValues() {
    return { min: Number(this.minRange.value), max: Number(this.maxRange.value) };
  }

  // public API: set values programmatically
  setValues(a, b) {
    this.minRange.value = a;
    this.maxRange.value = b;
    this.updateFromInputs();
  }
}

/*
// Exemple d'usage
document.addEventListener('DOMContentLoaded', () => {
  // initialisation simple
  const slider1 = new DualRangeSlider('#myRangeSlider', { gap: 0 });

  // accéder aux valeurs
  // console.log(slider1.getValues());

  // modifier les valeurs depuis le code
  // slider1.setValues(10, 50);
});
*/
/**
 * Crée le DOM du slider et instancie DualRangeSlider à partir d'options.
 * Retourne { instance, root } ou null si erreur.
 *
 * options = {
 *   container: selector|Element,    // obligatoire
 *   min: number, max: number,       // obligatoire (timestamps)
 *   valueMin: number, valueMax: number, // optionnel
 *   ms: boolean,                    // unité interne en ms
 *   gap: number,                    // minimal gap (same unit as min/max)
 *   classes: { root, slider, ... }  // opcional CSS classes overrides
 *   labels: { left, right }         // opcional text
 * }
 */
function createAndInitDualRange(options = {}) {
  if (!options.container) throw new Error('options.container required');
  const parent = (typeof options.container === 'string') ? document.querySelector(options.container) : options.container;
  if (!parent) throw new Error('Container element not found');

  if (typeof options.min === 'undefined' || typeof options.max === 'undefined') {
    throw new Error('options.min and options.max required');
  }

  const cls = Object.assign({
    root: 'slider-container',
    display: 'display-range',
    rangeWrap: 'range-wrap slider',
    sliderSel: 'slider',
    track: 'track',
    highlight: 'range-highlight',
    minRange: 'min-range',
    maxRange: 'max-range',
    values: 'values',
    minNumber: 'min-number',
    maxNumber: 'max-number',
  }, options.classes || {});

  // build root
  const root = document.createElement('div');
  root.className = cls.root;

  // labels
  const labels = document.createElement('div');
  labels.className = cls.display;
  root.appendChild(labels);

  // range wrap / slider
  const rangeWrap = document.createElement('div');
  rangeWrap.className = cls.rangeWrap;
  // set data-min/data-max as provided
  rangeWrap.dataset.min = String(options.min);
  rangeWrap.dataset.max = String(options.max);

  const track = document.createElement('div'); track.className = cls.track;
  const highlight = document.createElement('div'); highlight.className = cls.highlight;
  rangeWrap.appendChild(track);
  rangeWrap.appendChild(highlight);

  // inputs range
  const minR = document.createElement('input'); minR.type = 'range'; minR.className = cls.minRange;
  const maxR = document.createElement('input'); maxR.type = 'range'; maxR.className = cls.maxRange;
  minR.min = String(options.min); minR.max = String(options.max);
  maxR.min = String(options.min); maxR.max = String(options.max);
  minR.step = options.step ?? '1'; maxR.step = options.step ?? '1';
  minR.value = String(options.valueMin ?? options.min);
  maxR.value = String(options.valueMax ?? options.max);
  rangeWrap.appendChild(minR); rangeWrap.appendChild(maxR);
  root.appendChild(rangeWrap);

  // values area
  const values = document.createElement('div'); values.className = "w3-row";
  const minLabel = document.createElement('div'); minLabel.className = "w3-half";
  const minStrong = document.createElement('span'); minStrong.textContent = 'Min)';
  const minNum = document.createElement('input'); minNum.type = 'number'; minNum.className = cls.minNumber;
  minNum.min = String(options.min); minNum.max = String(options.max); minNum.value = String(options.valueMin ?? options.min); minNum.step = options.step ?? '1';
  minLabel.appendChild(minStrong); minLabel.appendChild(minNum);

  const maxLabel = document.createElement('div'); maxLabel.className = "w3-half w3-right-align";
  const maxStrong = document.createElement('span'); maxStrong.textContent = 'Max';
  const maxNum = document.createElement('input'); maxNum.type = 'number'; maxNum.className = cls.maxNumber;
  maxNum.min = String(options.min); maxNum.max = String(options.max); maxNum.value = String(options.valueMax ?? options.max);maxNum.step = options.step ?? '1';
  maxLabel.appendChild(maxStrong); maxLabel.appendChild(maxNum);

  values.appendChild(minLabel); values.appendChild(maxLabel);
  root.appendChild(values);

  // append to parent
  parent.appendChild(root);

  const instOptions = { gap: options.gap ?? 0, ms: Boolean(options.ms), callback: options.callback ?? null };
  const instance = new DualRangeSlider(root, instOptions);
  return instance;
}


