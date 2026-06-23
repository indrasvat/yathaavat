/* ============================================================================
   PHOSPHOR · terminal.js   (zero dependencies)
   The iconic "agent terminal" demo: a fake CLI/agent session that types a user
   prompt, shows thinking dots, streams tool-call lines, then prints a response.
   Optional tabs cycle through multiple scripted examples.

   USAGE
     <div id="demo"></div>
     <script src="terminal.js"></script>
     <script>
       phosphorTerminal(document.getElementById('demo'), {
         title: 'agent',                 // titlebar label
         examples: [{
           tab: 'Deploy',
           userMessage: 'Ship the api service to prod and watch the rollout.',
           thinkMs: 1600,
           tools: [
             { label: 'bash: tool build --release', durationMs: 1200 },
             { label: 'bash: tool deploy api --env prod', durationMs: 1400 },
             { label: 'write: rollout.log', durationMs: 900 },
           ],
           response: 'Deployed api@prod. Rollout healthy across 3 zones.',
         }],
       });
     </script>

   Wrap the container in `.crt-monitor` for the phosphor frame + scanlines.
   Colors come from tokens (--accent / --ink / --muted / --faint / --amber).
   ============================================================================ */
(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function phosphorTerminal(mount, opts) {
    opts = opts || {};
    var examples = opts.examples || [];
    if (!examples.length) return { stop: function () {} };
    var title = opts.title || "agent";
    var typeSpeed = opts.typeSpeed || 18; // ms per char
    var loop = opts.loop !== false;

    // ── scaffold ──
    mount.classList.add("pt");
    var root = el("div", "pt__root");
    var bar = el("div", "pt__bar");
    bar.appendChild(el("span", "pt__dot pt__dot--r"));
    bar.appendChild(el("span", "pt__dot pt__dot--y"));
    bar.appendChild(el("span", "pt__dot pt__dot--g"));
    bar.appendChild(el("span", "pt__title", title));
    root.appendChild(bar);

    var tabs = el("div", "pt__tabs");
    var tabEls = examples.map(function (ex, i) {
      var t = el("button", "pt__tab" + (i === 0 ? " is-active" : ""), ex.tab || "Example " + (i + 1));
      t.type = "button";
      tabs.appendChild(t);
      return t;
    });
    if (examples.length > 1) root.appendChild(tabs);

    var body = el("div", "pt__body");
    root.appendChild(body);
    mount.appendChild(root);

    injectStyles();

    var current = -1, timers = [], running = false;

    function clearTimers() { timers.forEach(clearTimeout); timers = []; }
    function wait(ms) { return new Promise(function (res) { timers.push(setTimeout(res, ms)); }); }

    function typeInto(node, text) {
      return new Promise(function (res) {
        var i = 0;
        (function step() {
          node.textContent = text.slice(0, i);
          if (i++ <= text.length) timers.push(setTimeout(step, typeSpeed));
          else res();
        })();
      });
    }

    function reduced() {
      return global.matchMedia && global.matchMedia("(prefers-reduced-motion: reduce)").matches;
    }

    async function play(idx) {
      running = true;
      current = idx;
      tabEls.forEach(function (t, i) { t.classList.toggle("is-active", i === idx); });
      body.innerHTML = "";
      var ex = examples[idx];

      // user prompt
      var userRow = el("div", "pt__user");
      var userText = el("span", "pt__user-text");
      userRow.appendChild(userText);
      body.appendChild(userRow);

      if (reduced()) { userText.textContent = ex.userMessage; }
      else { await typeInto(userText, ex.userMessage); }

      // thinking
      var think = el("div", "pt__think");
      think.innerHTML = '✦ Thinking <span class="pt__d thinking-1">.</span><span class="pt__d thinking-2">.</span><span class="pt__d thinking-3">.</span>';
      body.appendChild(think);
      await wait(reduced() ? 0 : (ex.thinkMs || 1500));
      think.classList.add("pt__think--done");
      think.innerHTML = "✓ Thinking";

      // tools
      var tools = ex.tools || [];
      for (var i = 0; i < tools.length; i++) {
        var line = el("div", "pt__tool");
        line.appendChild(el("span", "pt__prompt", "$"));
        line.appendChild(el("span", "pt__cmd", " " + tools[i].label));
        body.appendChild(line);
        scrollDown();
        await wait(reduced() ? 0 : tools[i].durationMs || 800);
        line.classList.add("is-done");
      }

      // response
      var resp = el("div", "pt__resp");
      body.appendChild(resp);
      if (reduced()) resp.textContent = ex.response;
      else await typeInto(resp, ex.response);
      var caret = el("span", "pt__caret blink", "▌");
      resp.appendChild(caret);
      scrollDown();

      running = false;
      if (loop && examples.length > 1) {
        await wait(2600);
        if (!running) play((idx + 1) % examples.length);
      }
    }

    function scrollDown() { body.scrollTop = body.scrollHeight; }

    tabEls.forEach(function (t, i) {
      t.addEventListener("click", function () { clearTimers(); play(i); });
    });

    play(0);

    return { stop: function () { clearTimers(); } };
  }

  var stylesInjected = false;
  function injectStyles() {
    if (stylesInjected) return;
    stylesInjected = true;
    var css = [
      ".pt__root{font-family:var(--font-mono);font-size:12px;line-height:1.7;color:var(--muted);text-align:left}",
      ".pt__bar{display:flex;align-items:center;gap:7px;padding:9px 12px;border-bottom:1px solid color-mix(in oklch,var(--accent) 18%,transparent)}",
      ".pt__dot{width:11px;height:11px;border-radius:50%}",
      ".pt__dot--r{background:#ff5f56}.pt__dot--y{background:#ffbd2e}.pt__dot--g{background:#27c93f}",
      ".pt__title{margin-left:8px;color:var(--faint);font-size:11px;letter-spacing:.04em}",
      ".pt__tabs{display:flex;gap:2px;padding:0 8px;border-bottom:1px solid color-mix(in oklch,var(--accent) 12%,transparent);overflow-x:auto}",
      ".pt__tab{background:none;border:0;color:var(--faint);font-family:var(--font-mono);font-size:11px;padding:8px 12px;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap;transition:color .15s}",
      ".pt__tab:hover{color:var(--muted)}",
      ".pt__tab.is-active{color:var(--accent-bright);border-bottom-color:var(--accent)}",
      ".pt__body{padding:18px 16px;min-height:240px;max-height:340px;overflow-y:auto;scrollbar-width:none}",
      ".pt__body::-webkit-scrollbar{display:none}",
      ".pt__user{border-left:2px solid var(--accent);padding-left:12px;margin-bottom:14px;color:var(--accent-bright)}",
      ".pt__think{color:var(--faint);margin-bottom:10px}",
      ".pt__think--done{color:var(--accent-dim)}",
      ".pt__tool{color:var(--muted);opacity:.55;transition:opacity .25s;white-space:pre-wrap;word-break:break-word}",
      ".pt__tool.is-done{opacity:.9}",
      ".pt__prompt{color:var(--accent)}",
      ".pt__resp{margin-top:12px;color:var(--ink);white-space:pre-wrap}",
      ".pt__caret{color:var(--accent);margin-left:1px}",
    ].join("");
    var s = document.createElement("style");
    s.textContent = css;
    document.head.appendChild(s);
  }

  global.phosphorTerminal = phosphorTerminal;
})(typeof window !== "undefined" ? window : this);
