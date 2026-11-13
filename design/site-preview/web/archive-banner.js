/* The LMMs-Lab banner, the one implementation every site uses. Framework-free: `html()` returns
   the markup (React renders it on the server, static sites insert it) and `mount()` adds the
   behaviour. Styles are in archive.css. tools/website/sync_archive.py copies this file from
   docs/brand/archive-design to each site; change it there. */
(function (root, factory) {
	if (typeof module === "object" && module.exports) module.exports = factory();
	else root.ArchiveBanner = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
	var ZH_PREFIX = "/zh-cn";
	var COPY = {
		en: { home: "Home", posts: "Posts", projects: "Projects", about: "About", login: "Log in", signup: "Sign up", account: "Account", other: "中文", otherLang: "zh-CN", menu: "Menu", main: "Main navigation", theme: "Switch theme" },
		zh: { home: "首页", posts: "文章", projects: "项目", about: "关于", login: "登录", signup: "注册", account: "账户", other: "English", otherLang: "en", menu: "菜单", main: "主导航", theme: "切换主题" },
	};
	var ROUTES = [["home", "/"], ["posts", "/posts/"], ["projects", "/projects/"], ["about", "/about/"]];
	var SUN = '<svg class="ar-theme-sun" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/></svg>';
	var MOON = '<svg class="ar-theme-moon" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true"><path d="M19.5 14.6A8 8 0 0 1 9.4 4.5a8 8 0 1 0 10.1 10.1Z"/></svg>';
	var ARROW = '<span aria-hidden="true">↗</span>';
	var SOCIAL = {
		github: { label: "GitHub", href: "https://github.com/EvolvingLMMs-Lab", icon: "M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" },
		discord: { label: "Discord", href: "https://discord.gg/JbxU88aZyZ", icon: "M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z" },
		x: { label: "X", href: "https://x.com/lmmslab", icon: "M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z" },
	};
	var EXTERNAL = ' target="_blank" rel="noopener noreferrer"';

	/* Icon links in the banner's order; `github` replaces the organisation link on a project's site. */
	function socialIcons(github) {
		return ["discord", "github", "x"].map(function (key) {
			var site = SOCIAL[key];
			var href = key === "github" && github ? github : site.href;
			return '<a href="' + href + '"' + EXTERNAL + ' aria-label="' + site.label + '" title="' + site.label + '"><svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><path d="' + site.icon + '"/></svg></a>';
		}).join("");
	}

	/* options: origin ("" on the lab site, its URL elsewhere), locale ("en" | "zh"), langHref, github. */
	function html(options) {
		var origin = options.origin || "";
		var locale = options.locale === "zh" ? "zh" : "en";
		var copy = COPY[locale];
		var url = function (path) { return origin + (locale === "zh" ? ZH_PREFIX : "") + path; };
		var nav = function (cls) {
			return ROUTES.map(function (route) {
				return '<a class="' + cls + '" data-ar-route="' + route[1] + '" href="' + url(route[1]) + '">' + copy[route[0]] + "</a>";
			}).join("");
		};
		var lang = function (cls) {
			return '<a class="' + cls + '" data-ar-lang lang="' + copy.otherLang + '" hreflang="' + copy.otherLang + '" href="' + (options.langHref || "/") + '">' + copy.other + "</a>";
		};
		return '<div class="ar-wrap ar-masthead-inner">' +
			'<div class="ar-masthead-left">' +
				'<a class="ar-logo" href="' + url("/") + '" aria-label="LMMs-Lab"><img src="/assets/logo-neon.png" alt="LMMs-Lab"></a>' +
				'<nav class="ar-nav" aria-label="' + copy.main + '">' + nav("ar-nav-link") + "</nav>" +
			"</div>" +
			'<div class="ar-masthead-right">' +
				'<div class="ar-social ar-desktop">' + socialIcons(options.github) + "</div>" +
				lang("ar-masthead-link ar-desktop") +
				'<button type="button" class="ar-theme" aria-label="' + copy.theme + '">' + SUN + MOON + "</button>" +
				'<div class="ar-desktop" data-ar-user></div>' +
				'<div class="ar-account ar-desktop" data-ar-account>' +
					'<a class="ar-masthead-link" href="' + url("/login/") + '">' + copy.login + "</a>" +
					'<a class="ar-btn ar-btn--header" href="' + url("/signup/") + '">' + copy.signup + " " + ARROW + "</a>" +
				"</div>" +
				'<button type="button" class="ar-menu-toggle" aria-expanded="false" aria-controls="ar-menu" aria-label="' + copy.menu + '"><i></i><i></i><i></i></button>' +
			"</div>" +
		"</div>" +
		'<nav id="ar-menu" class="ar-menu" aria-label="' + copy.menu + '" hidden>' +
			nav("ar-menu-link") +
			lang("ar-menu-link ar-menu-rule") +
			'<div data-ar-menu-user></div>' +
			'<div data-ar-menu-account>' +
				'<a class="ar-menu-link" href="' + url("/login/") + '">' + copy.login + "</a>" +
				'<a class="ar-menu-link ar-menu-signup" href="' + url("/signup/") + '">' + copy.signup + " " + ARROW + "</a>" +
			"</div>" +
			'<div class="ar-social ar-menu-social ar-menu-rule">' + socialIcons(options.github) + "</div>" +
		"</nav>";
	}

	/* options: toggleTheme(), navigate(href) for sites with client-side routing. */
	function mount(root, options) {
		/* Looked up on use: a framework may re-create the markup inside root. */
		function toggle() { return root.querySelector(".ar-menu-toggle"); }
		function menu() { return root.querySelector(".ar-menu"); }
		function setMenu(open) {
			toggle().setAttribute("aria-expanded", String(open));
			menu().hidden = !open;
		}
		function onRootClick(event) {
			if (event.target.closest(".ar-theme")) { options.toggleTheme(); return; }
			if (event.target.closest(".ar-menu-toggle")) { setMenu(menu().hidden); return; }
			var link = event.target.closest("a[href]");
			if (!link) return;
			setMenu(false);
			var internal = link.getAttribute("href").charAt(0) === "/";
			if (!options.navigate || !internal || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
			event.preventDefault();
			options.navigate(link.getAttribute("href"));
		}
		function onDocumentClick(event) {
			if (!menu().hidden && !root.contains(event.target)) setMenu(false);
		}
		function onKey(event) {
			if (event.key === "Escape" && !menu().hidden) { setMenu(false); toggle().focus(); }
		}
		var desktop = window.matchMedia("(min-width: 801px)");
		function onWidth(event) { if (event.matches) setMenu(false); }
		root.addEventListener("click", onRootClick);
		document.addEventListener("click", onDocumentClick);
		document.addEventListener("keydown", onKey);
		desktop.addEventListener("change", onWidth);
		return {
			/* Marks the current section and points the language link at this page's translation. */
			update: function (state) {
				var path = (state.path || "/").replace(ZH_PREFIX, "") || "/";
				if (path.charAt(path.length - 1) !== "/") path += "/";
				root.querySelectorAll("[data-ar-route]").forEach(function (link) {
					var route = link.getAttribute("data-ar-route");
					var active = route === "/" ? path === "/" : path.indexOf(route) === 0 || (route === "/posts/" && path.indexOf("/notes/") === 0);
					link.classList.toggle("is-active", active);
				});
				if (state.langHref) root.querySelectorAll("[data-ar-lang]").forEach(function (link) { link.setAttribute("href", state.langHref); });
			},
			destroy: function () {
				root.removeEventListener("click", onRootClick);
				document.removeEventListener("click", onDocumentClick);
				document.removeEventListener("keydown", onKey);
				desktop.removeEventListener("change", onWidth);
			},
		};
	}

	/* On the lab's other sites (options.origin set, as in html()), asks the lab site who is signed
	   in and shows their account tile, linking to the account page; the session cookie comes with
	   the request because the sites are same-site. Signed out, Log in and Sign up return here. */
	function account(root, options) {
		var origin = options.origin;
		if (!origin || typeof fetch !== "function") return;
		var copy = COPY[options.locale === "zh" ? "zh" : "en"];
		var back = "?next=" + encodeURIComponent(window.location.href);
		root.querySelectorAll('a[href$="/login/"], a[href$="/signup/"]').forEach(function (link) {
			link.setAttribute("href", link.getAttribute("href").split("?")[0] + back);
		});
		fetch(origin + "/api/me/", { credentials: "include" })
			.then(function (response) { return response.ok ? response.json() : null; })
			.then(function (data) {
				var user = data && data.user;
				if (!user) return;
				var name = String(user.name || copy.account);
				var page = origin + "/account/";
				var tile = document.createElement("a");
				tile.className = "ar-user";
				tile.href = page;
				tile.title = name;
				tile.setAttribute("aria-label", copy.account + ": " + name);
				var face = document.createElement("span");
				face.className = "ar-user-face";
				if (typeof user.avatar === "string" && user.avatar.indexOf("https://") === 0) {
					var image = document.createElement("img");
					image.src = user.avatar;
					image.alt = "";
					image.width = 40;
					image.height = 40;
					image.referrerPolicy = "no-referrer";
					face.appendChild(image);
				} else {
					var initial = document.createElement("span");
					initial.className = "ar-user-initial";
					initial.textContent = name.charAt(0).toUpperCase();
					face.appendChild(initial);
				}
				tile.appendChild(face);
				var item = document.createElement("a");
				item.className = "ar-menu-link ar-menu-rule";
				item.href = page;
				item.textContent = name;
				root.querySelectorAll("[data-ar-user]").forEach(function (slot) { slot.replaceChildren(tile.cloneNode(true)); });
				root.querySelectorAll("[data-ar-menu-user]").forEach(function (slot) { slot.replaceChildren(item.cloneNode(true)); });
			})
			.catch(function () { /* Signed-out controls stay when the lab site cannot be reached. */ });
	}

	/* The day or night choice, shared by every site under lmms-lab.com: a cookie on that domain
	   (a site's own storage is not readable from another site). get(): "light", "dark" or null;
	   set(value): keeps it for a year, or forgets it for any other value. */
	var THEME_COOKIE = "lmms-theme";
	function themeDomain() {
		return /(^|\.)lmms-lab\.com$/.test(location.hostname) ? "; Domain=.lmms-lab.com" : "";
	}
	var theme = {
		get: function () {
			var found = document.cookie.match(/(?:^|; )lmms-theme=(light|dark)(?:;|$)/);
			return found ? found[1] : null;
		},
		set: function (value) {
			var keep = value === "light" || value === "dark";
			document.cookie = THEME_COOKIE + "=" + (keep ? value : "") + themeDomain() + "; Path=/; SameSite=Lax; Max-Age=" + (keep ? 31536000 : 0);
		},
	};

	return {
		html: html,
		mount: mount,
		account: account,
		theme: theme,
		social: { github: SOCIAL.github.href, discord: SOCIAL.discord.href, x: SOCIAL.x.href },
	};
});
