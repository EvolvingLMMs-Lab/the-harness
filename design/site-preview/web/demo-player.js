/* Real recordings and trace events share the edited video's clock. */
(() => {
  const escape = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const clamp = (value, max) => Math.max(0, Math.min(max, value));
  const seconds = value => `${Number(value.toFixed(1))} s`;
  // Timeline coordinates: lane labels fill the left column, the plot runs from its edge to END.
  const VIEW = 640, END = 630, GAP = 14;
  const local = (value, zh) => typeof value === 'string' ? value : value[zh ? 'zh' : 'en'];
  // First render guesses the label column from the text (mono Latin about 0.6 em, CJK 1 em at
  // the 14-unit desktop size); mount() then measures the rendered labels and lays out again.
  const guess = labels => Math.ceil(Math.max(...labels.map(text =>
    [...text].reduce((width, c) => width + (c.codePointAt(0) > 0x2e7f ? 1 : .6), 0))) * 14) + GAP;

  function plot(demo, labels, left) {
    const width = END - left, bottom = demo.lanes.length * 24 + 6;
    const x = time => left + clamp(time, demo.duration) / demo.duration * width;
    const lanes = demo.lanes.map((lane, i) => {
      const y = 4 + i * 24;
      const marks = lane.events.map(event => {
        const start = x(event.start), end = x(event.end);
        const kind = lane.kind === 'model' ? 'd-model' : lane.kind === 'sense' ? 'd-reflex' : lane.kind === 'library' ? 'd-library' : 'd-prog';
        return end - start < 1 ? `<line x1="${start}" x2="${start}" y1="${y}" y2="${y+10}" class="${kind} d-event-tick"/>` : `<rect x="${start}" y="${y}" width="${end-start}" height="10" class="${kind}"/>`;
      }).join('');
      return `<text x="0" y="${y+9}" class="d-label">${escape(labels[i])}</text><line x1="${left}" x2="${END}" y1="${y+5}" y2="${y+5}" class="d-rule"/>${marks}`;
    }).join('');
    const axis = Array.from({length:6}, (_, i) => {
      const at = left + i * width / 5;
      return `<line x1="${at}" x2="${at}" y1="${bottom}" y2="${bottom+4}" class="d-axis"/><text x="${at}" y="${bottom+20}" class="d-tick ${i===5?'d-tick-end':i===0?'d-tick-start':''}">${seconds(demo.duration*i/5)}</text>`;
    }).join('');
    return `${lanes}<line x1="${left}" x2="${END}" y1="${bottom}" y2="${bottom}" class="d-axis"/>${axis}`;
  }
  const plotStyle = left => `--plot-left:${left/VIEW};--plot-width:${(END-left)/VIEW}`;

  // A recording is framed as a capture: four corner brackets, the last one magenta, and
  // the barcode in its lower right corner.
  const MARKS = '<span class="capture-marks" aria-hidden="true"><i></i><i></i><i></i><i></i></span>'
    + '<span class="archive-barcode screen-code" aria-hidden="true"></span>';

  function figure(id, {zh, overlay}) {
    const demo = window.HARNESS_DEMOS[id];
    // A short clip of the key moment has no lanes: the recording alone fills the panel.
    if (!demo.lanes.length) return `<figure class="archive-panel demo-figure demo-video demo-clip" data-demo="${id}">
      <div class="demo-screen"><video muted playsinline preload="none" poster="${demo.poster}" data-src="${demo.src}" aria-label="${escape(local(demo.title, zh))}"></video>${MARKS}</div></figure>`;
    const labels = demo.lanes.map(lane => local(lane.label, zh));
    const left = guess(labels), bottom = demo.lanes.length * 24 + 6;
    const title = escape(local(demo.title, zh));
    return `<figure class="archive-panel demo-figure demo-video" data-demo="${id}">
      <div class="demo-screen"><video muted playsinline preload="none" poster="${demo.poster}" data-src="${demo.src}" aria-label="${title}"></video>${MARKS}</div>
      <div class="demo-track">${overlay}<div class="demo-timeline-control" style="${plotStyle(left)}">
      <svg class="demo-timeline" viewBox="0 0 ${VIEW} ${bottom+28}" data-left="${left}" aria-hidden="true"><g class="demo-plot">${plot(demo, labels, left)}</g><g class="demo-cursor" transform="translate(${left} 0)"><line y1="0" y2="${bottom+4}" class="d-playhead"/><path d="M-4 0H4L0 5Z" class="demo-cursor-cap"/></g></svg>
      <input class="demo-seek" type="range" min="0" max="${demo.duration}" step="0.01" value="0" aria-label="${zh?'拖动定位':'Seek'}: ${title}" aria-valuetext="0 / ${seconds(demo.duration)}">
      </div></div></figure>`;
  }

  // Sizes the label column to the widest rendered label; the label size changes with the layout.
  function fit(figureEl, zh) {
    const svg = figureEl.querySelector('.demo-timeline');
    const widest = Math.max(0, ...[...svg.querySelectorAll('.d-label')].map(text => text.getComputedTextLength()));
    if (!widest) return false;
    const left = Math.ceil(widest) + GAP;
    if (left === Number(svg.dataset.left)) return false;
    const demo = window.HARNESS_DEMOS[figureEl.dataset.demo];
    svg.querySelector('.demo-plot').innerHTML = plot(demo, demo.lanes.map(lane => local(lane.label, zh)), left);
    svg.dataset.left = String(left);
    figureEl.querySelector('.demo-timeline-control').setAttribute('style', plotStyle(left));
    return true;
  }

  function mount(stage, tablist, zh) {
    const tabs = [...stage.querySelectorAll('.stage-item>h3>[role=tab]')];
    const panels = tabs.map(tab => document.getElementById(tab.getAttribute('aria-controls')));
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    let selected = 0, visible = false;
    const players = panels.map((panel, index) => {
      const figureEl = panel.querySelector('[data-demo]');
      const demo = window.HARNESS_DEMOS[figureEl.dataset.demo];
      const video = figureEl.querySelector('video'), seek = figureEl.querySelector('.demo-seek');
      // A clip without lanes has no timeline: the stage bar alone shows its progress.
      const svg = figureEl.querySelector('.demo-timeline'), cursor = figureEl.querySelector('.demo-cursor');
      const progress = tabs[index].closest('.stage-item').querySelector('.stage-progress');
      // playing: the media itself is running toward its end, not paused or held by a drag.
      let position = 0, dragging = false, resume = false, frame = 0, wantsPlay = false, playing = false;
      const active = () => index === selected && visible && !document.hidden;
      const paint = () => {
        if (!dragging && video.readyState > 0) position = clamp(video.currentTime, demo.duration);
        if (svg) {
          const left = Number(svg.dataset.left);
          seek.value = String(position);
          seek.setAttribute('aria-valuetext', `${seconds(position)} / ${seconds(demo.duration)}`);
          cursor.setAttribute('transform', `translate(${left + position / demo.duration * (END - left)} 0)`);
        }
        progress.style.width = `${position / demo.duration * 100}%`;
      };
      const animate = () => { paint(); if (!video.paused && active()) frame = requestAnimationFrame(animate); };
      const load = () => {
        if (!video.hasAttribute('src')) { video.src = video.dataset.src; video.load(); }
      };
      const play = () => {
        wantsPlay = true; load();
        if (active()) video.play().catch(() => { wantsPlay = false; paint(); });
      };
      const sync = () => {
        cancelAnimationFrame(frame);
        if (!active()) { video.pause(); return; }
        if (wantsPlay && !dragging) play();
      };
      // Leaving a demo returns it to the start: its source, playhead and stage bar reset.
      const release = () => {
        wantsPlay = false; dragging = false; playing = false; video.pause(); cancelAnimationFrame(frame);
        if (video.hasAttribute('src')) { video.removeAttribute('src'); video.load(); }
        position = 0; paint();
      };
      const toggle = () => {
        if (video.paused) { if (position >= demo.duration-.05) { position=0; if(video.readyState)video.currentTime=0; } play(); }
        else { wantsPlay=false; video.pause(); }
      };
      video.addEventListener('click', toggle);
      if (seek) {
        seek.addEventListener('pointerdown', () => {
          dragging = true; resume = !video.paused; video.pause(); load();
        });
        seek.addEventListener('input', () => {
          position = clamp(Number(seek.value), demo.duration); load();
          if (video.readyState > 0) video.currentTime = position;
          paint();
        });
        const endDrag = () => {
          if (!dragging) return;
          dragging = false; if(resume)play(); paint();
        };
        window.addEventListener('pointerup', endDrag);
        window.addEventListener('pointercancel', endDrag);
        seek.addEventListener('keydown', load);
      }
      video.addEventListener('loadedmetadata', () => { video.currentTime=clamp(position,video.duration); paint(); });
      video.addEventListener('play', () => { playing = true; cancelAnimationFrame(frame); animate(); });
      // A natural end also pauses the media, just before 'ended'; only other pauses stop it playing.
      video.addEventListener('pause', () => { if (!video.ended) playing = false; cancelAnimationFrame(frame); paint(); });
      video.addEventListener('timeupdate', paint);
      video.addEventListener('seeked', paint);
      video.addEventListener('ended', () => {
        // A recording that plays to its end hands over to the next, whatever was clicked before;
        // seeking to the end while paused or dragging does not count as playing to the end.
        const finished = playing && !dragging; playing = false; wantsPlay = false; paint();
        if (finished && !reduced.matches) show((selected+1)%tabs.length);
      });
      video.addEventListener('error', () => {
        wantsPlay=false;
        video.setAttribute('aria-label',zh?'视频加载失败，请重试':'Video unavailable. Try again.');
      });
      // Choosing a demo plays it from the start; reduced motion keeps the poster until asked.
      return {sync,release,paint,figure:figureEl,activate:() => {wantsPlay=!reduced.matches;sync();}};
    });
    function show(index) {
      if(index!==selected)players[selected].release();
      selected=index;
      tabs.forEach((tab,i) => {
        const on=i===index;tab.setAttribute('aria-selected',String(on));tab.tabIndex=on?0:-1;
        tab.closest('.stage-item').classList.toggle('on',on);panels[i].classList.toggle('on',on);
        panels[i].inert=!on;
      });
      players[index].activate();
    }
    tablist(tabs,show);
    const observer=new IntersectionObserver(entries => {visible=entries[0].isIntersecting;players[selected].sync();},{threshold:0.1});
    observer.observe(stage);
    document.addEventListener('visibilitychange',()=>players[selected].sync());
    reduced.addEventListener('change',()=> {players.forEach(p=>p.release()); players[selected].activate();});
    // Every item's detail keeps the height of the tallest one, so choosing another item never
    // changes the stage's height and the page below it stays where it is.
    const list = stage.querySelector('.stage-list');
    const details = tabs.map(tab => tab.closest('.stage-item').querySelector('.stage-detail'));
    const level = () => {
      stage.classList.add('stage-measure');
      const tallest = Math.ceil(Math.max(0, ...details.map(detail => detail.getBoundingClientRect().height)));
      stage.classList.remove('stage-measure');
      if (list.style.getPropertyValue('--stage-detail') !== `${tallest}px`) list.style.setProperty('--stage-detail', `${tallest}px`);
    };
    const refit = () => { level(); players.forEach(p => { if (p.figure.querySelector('.demo-timeline') && fit(p.figure, zh)) p.paint(); }); };
    new ResizeObserver(refit).observe(stage);
    document.fonts.ready.then(refit);
    level();
    show(0);
  }
  window.HarnessDemos={figure,mount};
})();
