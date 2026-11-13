// The lab logo's Echo animation, the same one the lab site plays: on load, four echo layers
// slide out once from behind the letters and the X, then the logo rests; nothing loops.
// Rendering comes from animation/lmms-logo-cyber.js (copied from the lab site by
// tools/website/sync_archive.py). The static PNG stays visible until the first canvas frame
// is drawn, and stays for good when the scripts fail to load. Reduced motion draws the
// rested logo at once.
//
// The canvas sits in a 132 x 44 box, the size the engine draws the header lockup at. In the
// shared banner, which the homepage and the docs both use, archive.css scales any
// `.ar-logo > *` child from that box to the logo width.
(function () {
	var FADE = 'opacity 0.15s ease';
	var SCRIPTS = ['/animation/lmms-pixelfont.js', '/animation/lmms-logo-cyber.js'];
	var loading = null;

	function loadScripts() {
		if (!loading) {
			loading = Promise.all(SCRIPTS.map(function (src) {
				return new Promise(function (resolve, reject) {
					var s = document.createElement('script');
					s.src = src;
					s.async = false;
					s.onload = function () { resolve(); };
					s.onerror = function () { reject(new Error('failed to load ' + src)); };
					document.head.appendChild(s);
				});
			}));
		}
		return loading;
	}

	function attach(logo) {
		var img = logo.querySelector('img');
		if (!img || logo.dataset.logoMotion) return;
		logo.dataset.logoMotion = 'on';
		var box = document.createElement('span');
		box.setAttribute('aria-hidden', 'true');
		box.style.cssText = 'position:absolute;left:0;top:0;width:132px;height:44px;pointer-events:none';
		var canvas = document.createElement('canvas');
		canvas.style.cssText = 'position:absolute;left:0;top:0;display:block;width:132px;height:44px;opacity:0;transition:' + FADE;
		box.appendChild(canvas);
		logo.style.position = 'relative';
		logo.appendChild(box);

		var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
		loadScripts().then(function () {
			if (!window.LMMSCyber) return;
			window.LMMSCyber.attach(canvas, { variant: 'e', size: 'header', mode: 'live', palette: 'neon', reduced: reduced });
			// The engine paints on its next animation frame; swap after that.
			requestAnimationFrame(function () {
				requestAnimationFrame(function () {
					canvas.style.opacity = '1';
					img.style.transition = FADE;
					img.style.opacity = '0';
				});
			});
		}).catch(function (error) {
			console.warn('Header logo animation did not load; showing the static logo.', error);
		});
	}

	function run() {
		document.querySelectorAll('.ar-masthead .ar-logo').forEach(attach);
	}
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run);
	else run();
})();
