/* EcoServing live demo (/demo): drives four iframes like four people using the real site.
 *
 * Each pane is a normal browser frame, logged in as one role. This script moves a visible cursor, types into
 * the real forms and clicks the real buttons. Panes wait for each other (signal / waitFor) so a supplier's offer
 * exists before the shelter claims it, and so on. Add ?speed=3 to run faster while testing, ?autostart=1 to skip
 * the start screen, ?pace=1 for quicker cursor and typing, ?beat=2 for shorter pauses after each caption
 * (seconds; the default 4 leaves time to talk about each step). P pauses and resumes everything.
 */
(() => {
  'use strict';

  window.__demo = {log: []};              // exposed for testing: step timestamps
  // Timing options come from `python run_demo.py --speed ...` (handed to the page by the server), and the address
  // can override them (?speed=2). Either way, opening plain /demo uses what the command line set.
  const query = new URLSearchParams(location.search);
  let defaults = {};
  try { defaults = JSON.parse(document.body.dataset.options || '{}'); } catch (e) { /* no server options */ }
  const params = {
    has: (k) => query.has(k) || k in defaults,
    get: (k) => (query.has(k) ? query.get(k) : (k in defaults ? String(defaults[k]) : null)),
  };
  const SPEED = Math.max(0.5, parseFloat(params.get('speed')) || 1);
  const PACE = Math.max(0.5, parseFloat(params.get('pace')) || 1.5);   // >1 slows every pause and keystroke down
  const BEAT = (params.has('beat') ? Math.max(0, parseFloat(params.get('beat')) || 0) : 4) * 1000;   // pause after each caption
  const GAP = 900;                         // a breath after each click or finished field
  window.__demo.settings = {SPEED, PACE, BEAT};   // for testing
  const FRAME_W = 1180;                   // each pane shows the site at this width, scaled to fit
  const ROLES = ['supplier', 'distributor', 'volunteer', 'consumer'];
  const $ = (s, r = document) => r.querySelector(s);
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();

  // ---- run control ------------------------------------------------------------------------------
  let run = null;                          // {id, aborted, events, startedAt}
  class Stopped extends Error {}

  // One timer per wait. Pausing stops the timers that are running and re-arms them with the time that was left.
  const wait = (total) => new Promise((resolve, reject) => {
    const r = run;
    let left = total, armedAt = 0, timer = null;
    const entry = {
      pause() { clearTimeout(timer); left -= performance.now() - armedAt; },
      resume() { armedAt = performance.now(); timer = setTimeout(finish, Math.max(0, left)); },
    };
    const finish = () => { r.waiters.delete(entry); resolve(); };
    r.waiters.add(entry);
    if (!r.paused) entry.resume(); else armedAt = performance.now();
    r.aborted.then(() => { clearTimeout(timer); r.waiters.delete(entry); reject(new Stopped()); }, () => {});
  });
  const sleep = (ms) => wait((ms * PACE) / SPEED);
  const beat = (extra = 0) => wait(Math.max(BEAT, extra * PACE) / SPEED);
  const evt = (name) => {
    if (!run.events.has(name)) { let resolve; const p = new Promise((r) => { resolve = r; }); run.events.set(name, {p, resolve}); }
    return run.events.get(name);
  };
  const signal = (name) => evt(name).resolve();
  const waitFor = (name) => Promise.race([evt(name).p, run.aborted.then(() => { throw new Stopped(); })]);

  const pad = (n) => String(n).padStart(2, '0');
  const inHours = (h) => {                 // value for <input type="datetime-local">, h hours from now
    const d = new Date(Date.now() + h * 3600e3);
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  // ---- one pane: an iframe, a cursor and a caption ------------------------------------------------
  class Pane {
    constructor(el) {
      this.el = el;
      this.role = el.dataset.role;
      this.screen = $('.pane-screen', el);
      this.frame = $('iframe', el);
      this.cursor = $('.cursor', el);
      this.captionEl = $('.pane-caption', el);
      this.scale = 1;
      this.tempo = (this.role === 'admin' && parseFloat(params.get('admin'))) || parseFloat(el.dataset.tempo) || 1;   // >1 makes this pane's cursor, typing and pauses quicker
      this.layout();
    }

    sleep(ms) { return sleep(ms / this.tempo); }
    wait(ms) { return wait(ms / SPEED / this.tempo); }
    beat(extra = 0) { return wait(Math.max(BEAT, extra * PACE) / SPEED / this.tempo); }

    layout() {
      const w = this.screen.clientWidth, h = this.screen.clientHeight;
      this.scale = w / FRAME_W;
      this.frame.style.width = `${FRAME_W}px`;
      this.frame.style.height = `${h / this.scale}px`;
      this.frame.style.transform = `scale(${this.scale})`;
    }

    get doc() { return this.frame.contentDocument; }

    nextLoad(timeout = 12000) {
      return new Promise((resolve) => {
        const t = setTimeout(resolve, timeout);
        this.frame.addEventListener('load', () => { clearTimeout(t); resolve(); }, {once: true});
      });
    }

    async go(path) {
      const loaded = this.nextLoad();
      this.frame.src = `/demo/frame/${this.role}${path}`;
      await loaded;
      await this.sleep(300);                    // let the page's scripts and animations settle
    }

    async reload() {
      const loaded = this.nextLoad();
      this.doc.location.reload();
      await loaded;
      await this.sleep(300);
    }

    async caption(text, hold = 0) {
      this.captionEl.classList.add('swap');
      await this.sleep(150);
      this.captionEl.textContent = text;
      window.__demo.log.push([this.role, Math.round((Date.now() - run.startedAt) / 100) / 10, text]);
      this.captionEl.classList.remove('swap');
      this.el.classList.add('active');
      setTimeout(() => this.el.classList.remove('active'), 3200 / SPEED);
      await this.beat(hold);                    // time for the presenter to explain this step
    }

    /** Find an element by CSS selector (and optional visible text), waiting for it to appear. */
    async need(target, tries = 40) {
      if (target instanceof Element) return target;
      const [sel, text] = Array.isArray(target) ? target : [target, null];
      for (let i = 0; i < tries; i++) {
        const d = this.doc;
        if (d) {
          const els = [...d.querySelectorAll(sel)];
          const hit = text == null ? els[0] : els.find((e) => norm(e.textContent).toLowerCase().includes(text.toLowerCase()));
          if (hit) return hit;
        }
        await new Promise((r) => setTimeout(r, 250));
      }
      throw new Error(`${this.role}: could not find ${sel}${Array.isArray(target) ? ` with "${target[1]}"` : ''}`);
    }

    async move(el) {
      const view = this.frame.contentWindow;
      const r0 = el.getBoundingClientRect();
      if (r0.top < 70 || r0.bottom > view.innerHeight - 20) {
        el.scrollIntoView({block: 'center', behavior: 'smooth'});
        await this.sleep(450);
      }
      const r = el.getBoundingClientRect();
      const x = (r.left + Math.min(r.width / 2, 150)) * this.scale;
      const y = (r.top + Math.min(r.height / 2, 24)) * this.scale;
      this.cursor.style.opacity = '1';
      this.cursor.style.transform = `translate(${x}px, ${y}px)`;
      await this.sleep(550);
    }

    async click(target, {nav = false} = {}) {
      const el = await this.need(target);
      await this.move(el);
      this.cursor.classList.add('click');
      await this.sleep(110);
      this.cursor.classList.remove('click');
      const loaded = nav ? this.nextLoad() : null;
      el.click();
      if (nav) { await loaded; await this.sleep(300); } else { await this.sleep(200); }
      await this.wait(GAP);
    }

    async type(target, text) {
      const el = await this.need(target);
      await this.move(el);
      el.focus();
      el.value = '';
      for (const ch of text) {
        el.value += ch;
        el.dispatchEvent(new Event('input', {bubbles: true}));
        await this.sleep(13 + Math.random() * 14);
      }
      await this.sleep(120);
      await this.wait(GAP);
    }

    async setValue(target, value) {           // selects, dates and numbers: set directly after moving there
      const el = await this.need(target);
      await this.move(el);
      el.value = value;
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      await this.sleep(200);
      await this.wait(GAP * 0.6);
    }

    async check(target) {
      const el = await this.need(target);
      await this.move(el);
      if (!el.checked) el.click();
      await this.sleep(200);
    }

    async scroll(by) {
      this.frame.contentWindow.scrollBy({top: by, behavior: 'smooth'});
      await this.sleep(700);
    }
  }

  // ---- the story: what each person does ----------------------------------------------------------
  const S = sleep;
  const send = (P) => P.click('#chat-form button[type=submit]');
  const openChat = async (P, who) => {
    await P.go('/messages');
    await S(900);
    await P.click(['.conv-list a', who], {nav: true});
  };

  const script = {
    // Sunrise Bakery: posts surplus bread, pledges to a shelter's request, answers chats.
    async supplier(P) {
      await P.go('/_demo_login');
      await P.caption('Sunrise Bakery has bread left at closing time.', 1600);
      await P.caption('A supplier posts a surplus food offer in seconds.');
      await P.click(['a.btn', 'Post food offer'], {nav: true});
      await P.type('#title', 'Evening sourdough & rolls');
      await P.type('#description', 'Sourdough loaves and soft rolls baked today.');
      await P.setValue('#food_type', 'Bakery & bread');
      await P.type('#quantity', 'About 30 items');
      await P.setValue('#pickup_deadline', inHours(4));
      await P.click(['button', 'Post offer'], {nav: true});
      signal('offerPosted');
      await P.caption('Live. Verified distributors can see it right away.', 2000);

      await waitFor('requestPosted');
      await P.caption('Meanwhile a shelter is asking for bread. We can help.');
      await P.go('/food-requests');
      await S(1200);
      await P.click(['a.post-card', 'Fresh bread for Saturday'], {nav: true});
      await S(1500);
      await P.click(['button', 'Pledge to help'], {nav: true});
      await P.caption('Pledged. The shelter can see who is helping.', 2600);

      await P.go('/offers');
      await P.caption('Back on our offers, we wait for a taker.');
      await waitFor('claimed');
      await P.reload();
      await P.caption('Claimed by Harbor Street Shelter.', 1800);

      await waitFor('distMsg');
      await P.caption('Chat: the shelter wants to arrange pickup.');
      await openChat(P, 'Harbor Street');
      await S(1200);
      await P.type('#body', 'Perfect! Ring the back door at 6pm and ask for Maria.');
      await send(P);
      signal('supReplied');
      await P.caption('Replies show up live on the other screen.', 2200);

      await waitFor('consumerMsg');
      await P.caption('A neighbor reserved our small muffin box too.');
      await openChat(P, 'Jordan');
      await S(1000);
      await P.type('#body', 'Hi Jordan! The box is at the counter. Come by before 5pm.');
      await send(P);
      signal('supReplied2');
      signal('supplierDone');
      await P.caption('Food rescued. Nothing wasted.', 2500);
      await waitFor('adminDone');
      await P.caption('Suppliers can report scams too. Admins keep the network safe.', 5000);
    },

    // Harbor Street Shelter: requests food and volunteers, claims an offer, runs the chats.
    async distributor(P) {
      await P.go('/_demo_login');
      await P.caption('Harbor Street Shelter feeds about 60 people a night.', 1600);
      await P.caption('A verified distributor posts what it needs.');
      await P.click(['a.btn', 'Request food'], {nav: true});
      await P.type('#title', 'Fresh bread for Saturday breakfast');
      await P.type('#description', 'Loaves or rolls for about 60 guests.');
      await P.type('#quantity', '40 loaves');
      await P.setValue('#needed_by', inHours(30));
      await P.click(['button', 'Post request'], {nav: true});
      signal('requestPosted');
      await P.caption('Request posted. Suppliers can pledge to fill it.', 2000);

      await P.caption('It also needs a driver, so it asks for volunteers.');
      await P.go('/volunteer/new');
      await P.type('#title', 'Bread pickup driver');
      await P.type('#tasks', 'Collect bread from Sunrise Bakery and drive it to the shelter.');
      await P.type('#requirements', 'Own car');
      await P.setValue('#start_time', inHours(5));
      await P.setValue('#end_time', inHours(7));
      await P.setValue('#slots', '1');
      await P.click(['button', 'Post request'], {nav: true});
      signal('volReqPosted');
      await P.caption('Volunteer request posted.', 1500);

      await waitFor('offerPosted');
      await P.caption('New food offers appear for verified distributors.');
      await P.go('/offers');
      await S(1200);
      await P.click(['a.post-card', 'Evening sourdough'], {nav: true});
      await S(1200);
      await P.caption('Claim it. The food is reserved for us.');
      await P.click(['button', 'Claim offer'], {nav: true});
      signal('claimed');
      await S(900);
      await P.caption('Then agree on pickup in chat.');
      await P.click(['a.btn', 'Message supplier'], {nav: true});
      await P.type('#body', 'We will collect at 6pm. Could you set aside two bags?');
      await send(P);
      signal('distMsg');

      await waitFor('volApplied');
      await P.caption('Back to the volunteer request: someone signed up.');
      await P.go('/volunteer?mine=1');
      await P.click(['a.post-card', 'Bread pickup driver'], {nav: true});
      await P.caption('A volunteer signed up. Accept them.');
      await P.click(['button', 'Accept'], {nav: true});
      await P.caption('Confirmed. Now a quick message.');
      await P.click('a[aria-label^="Message"]', {nav: true});
      await P.type('#body', 'Thanks Sam! Pickup is at 5pm at Sunrise Bakery.');
      await send(P);
      signal('accepted');
      await S(800);

      await waitFor('supReplied');
      signal('distributorDone');
      await P.caption('The bakery replied. Pickup is set.', 2500);
      await waitFor('adminDone');
      await P.caption('Shelters stay protected: every report goes to an admin.', 5000);
    },

    // Sam Rivera: browses shifts, signs up for one, gets confirmed and chats.
    async volunteer(P) {
      await P.go('/_demo_login');
      await P.caption('Sam has a car and free evenings.', 1600);
      await P.caption('Volunteers browse shifts that need help.');
      await P.go('/volunteer');
      await S(1500);
      await P.scroll(300);
      await P.click(['a.post-card', 'Sort and pack'], {nav: true});
      await P.caption('Every shift lists the tasks, time and place.', 2000);
      await P.go('/dashboard');
      await P.caption('Sam waits for something that fits.');
      await P.scroll(380);
      await S(800);

      await waitFor('volReqPosted');
      await P.go('/volunteer');
      await P.caption('A new request just appeared: a driver is needed.');
      await S(1500);
      await P.click(['a.post-card', 'Bread pickup driver'], {nav: true});
      await S(1200);
      await P.type('#message', 'I have a car and can do 5pm!');
      await P.click(['button', 'Sign up'], {nav: true});
      signal('volApplied');
      await P.caption('Signed up. Waiting for the organizer to confirm.');
      await P.go('/dashboard');
      await P.caption('The sign-up shows as pending on Sam’s dashboard.');
      await P.scroll(380);
      await S(1200);

      await waitFor('accepted');
      await P.go('/dashboard');
      await P.caption('Accepted! The shift is confirmed, and the shelter wrote.', 1500);
      await openChat(P, 'Harbor Street');
      await P.type('#body', 'See you at 5pm. Bags and gloves packed!');
      await send(P);
      signal('volunteerDone');
      await P.caption('Everyone knows the plan.', 2500);
      await waitFor('adminDone');
      await P.caption('Volunteers can report anything that feels wrong.', 5000);
    },

    // Jordan Lee: browses small free offers, reserves one and chats with the bakery.
    async consumer(P) {
      await P.go('/_demo_login');
      await P.caption('Jordan lives nearby and could use a free snack.', 1600);
      await P.caption('Consumers only see small offers meant for individuals.');
      await P.go('/offers');
      await S(1500);
      await P.type('input[name=q]', 'muffin');
      await P.click(['button', 'Filter'], {nav: true});
      await P.caption('Search finds a box of muffins from Sunrise Bakery.', 1800);
      await P.click(['a.post-card', 'Box of 6 muffins'], {nav: true});
      await S(1800);
      await P.caption('Reserve it. It is Jordan’s until pickup.');
      await P.click(['button', 'Reserve'], {nav: true});
      await S(1500);
      await P.caption('A quick thank-you message to the bakery.');
      await P.click(['a.btn', 'Message supplier'], {nav: true});
      await P.type('#body', 'Thank you! I will pick the muffins up by 5pm.');
      await send(P);
      signal('consumerMsg');

      await waitFor('supReplied2');
      await P.caption('The bakery answered. Breakfast sorted.', 2500);

      // Finale: a scam post shows up and Jordan reports it.
      await Promise.all([waitFor('supplierDone'), waitFor('distributorDone'), waitFor('volunteerDone')]);
      await P.caption('Then Jordan sees a post that looks wrong.');
      const token = $('meta[name=csrf-token]').content;
      await fetch('/demo/plant-scam', {method: 'POST', headers: {'X-CSRF-Token': token}});
      await P.go('/offers');
      await S(2200);
      await P.click(['a.post-card', 'pay $15'], {nav: true});
      await P.caption('Real food here is always free. Asking for a fee is a red flag.', 3200);
      await P.click(['a.report-link', 'Report'], {nav: true});
      await P.caption('Anyone can report a scam or fraud in seconds.', 1500);
      await P.check('input[name=category][value=scam]');
      await P.type('#details', 'They want a $15 delivery fee by gift card before I can pick up free food.');
      await P.click(['button', 'Send report'], {nav: true});
      await P.caption('Report sent. The admins are notified.', 2500);
      signal('reported');

      await waitFor('adminDone');
      await P.go('/offers');
      await P.caption('The scam post is gone. Neighbors stay safe.', 5000);
    },

    // An EcoServing admin, shown in a window in the middle of the screen once a report arrives.
    async admin(P) {
      await waitFor('reported');
      await showAdmin(P);
      await P.go('/_demo_login?next=/admin/reports');
      await P.caption('Admin view: the new scam report arrives instantly.', 3200);
      await P.scroll(220);
      await P.caption('Admins read the details and see who sent the report.', 3200);
      await P.caption('Step 1: take the scam post down.');
      await P.click(['button', 'Take down post']);
      await P.sleep(700);
      await P.click(['button', 'Click again'], {nav: true});
      await P.caption('The post is no longer visible to anyone.', 1800);
      await P.caption('Step 2: suspend the account so it cannot post again.');
      await P.click(['button', 'Suspend account']);
      await P.sleep(700);
      await P.click(['button', 'Click again'], {nav: true});
      await P.caption('Step 3: close the report with a note.');
      await P.setValue('select[name=status]', 'resolved');
      await P.type('input[name=admin_note]', 'Gift-card scam. Post removed, account suspended.');
      await P.click(['button', 'Save'], {nav: true});
      await P.click(['a.btn', 'Resolved'], {nav: true});
      await P.caption('Resolved. Every action is logged for the team.', 3000);
      signal('adminDone');
      await P.sleep(2500);
      hideAdmin(P);
    },
  };

  const showAdmin = async (P) => {
    P.el.classList.add('show');
    await sleep(400);
    P.layout();
  };
  const hideAdmin = (P) => P.el.classList.remove('show');

  // ---- page chrome: start, stop, clock -----------------------------------------------------
  const panes = [...document.querySelectorAll('.pane')].map((el) => new Pane(el));
  const overlay = $('#overlay'), clock = $('#clock');
  let ticker = null;

  const relayout = () => panes.forEach((p) => p.layout());
  addEventListener('resize', relayout);

  function tick() {
    if (run.paused) return;
    const s = (Date.now() - run.startedAt - run.pausedFor) / 1000 * SPEED;
    clock.textContent = `${Math.floor(s / 60)}:${pad(Math.floor(s % 60))}`;
  }

  function togglePause() {
    if (!run || run.done) return;
    run.paused = !run.paused;
    if (run.paused) { run.pausedAt = Date.now(); run.waiters.forEach((w) => w.pause()); }
    else { run.pausedFor += Date.now() - run.pausedAt; run.waiters.forEach((w) => w.resume()); }
    $('#pause').textContent = run.paused ? 'Resume (P)' : 'Pause (P)';
    document.body.classList.toggle('paused', run.paused);
  }

  function stop() {
    if (!run || run.done) return;
    run.done = true;       // `run` stays set so steps that are still unwinding never see null
    document.body.classList.remove('paused');
    $('#pause').textContent = 'Pause (P)';
    run.abort();
    clearInterval(ticker);
  }

  async function start() {
    stop();
    overlay.hidden = true;
    panes.forEach((p) => { p.captionEl.textContent = ''; p.cursor.style.opacity = '0'; p.frame.src = 'about:blank'; });
    $('.pane-admin').classList.remove('show');
    relayout();
    let abort;
    const aborted = new Promise((_, reject) => { abort = () => reject(new Stopped()); });
    aborted.catch(() => {});
    const mine = run = {aborted, abort, events: new Map(), waiters: new Set(), startedAt: Date.now(), paused: false, pausedFor: 0, pausedAt: 0};
    window.__demo.log.length = 0;
    ticker = setInterval(tick, 500);
    tick();
    try {
      const token = $('meta[name=csrf-token]').content;
      await fetch('/demo/reset', {method: 'POST', headers: {'X-CSRF-Token': token}});   // fresh demo data every run
      await Promise.all(panes.map(async (p) => {
        try {
          await script[p.role](p);
        } catch (e) {
          if (e instanceof Stopped) return;
          console.error('[demo]', p.role, e);
          p.captionEl.textContent = `(demo step failed: ${e.message})`;
        }
      }));
      if (run === mine && !mine.done) {
        clearInterval(ticker);
        await new Promise((r) => setTimeout(r, 1200 / SPEED));
        $('#overlay-title').textContent = 'That is EcoServing.';
        $('#overlay-text').textContent = 'Surplus food moved from a bakery to a shelter, a volunteer and a neighbor in a few minutes, and when a scam appeared an admin removed it. Every screen was the real app.';
        $('#start').textContent = 'Watch again';
        overlay.hidden = false;
        mine.done = true;
      }
    } catch (e) {
      if (!(e instanceof Stopped)) console.error('[demo]', e);
    }
  }

  $('#start').addEventListener('click', start);
  $('#restart').addEventListener('click', start);
  $('#pause').addEventListener('click', togglePause);
  $('#fullscreen').addEventListener('click', toggleFullscreen);
  function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen?.();
  }
  addEventListener('keydown', (e) => {
    if (e.key === 'f' || e.key === 'F') toggleFullscreen();
    else if (e.key === 'p' || e.key === 'P') togglePause();
    else if ((e.key === ' ' || e.key === 'Enter') && !overlay.hidden) { e.preventDefault(); start(); }
    else if (e.key === 'Escape' && run && !run.done) { stop(); overlay.hidden = false; $('#start').textContent = 'Start the demo'; }
  });

  window.__demo.start = start; window.__demo.stop = stop; window.__demo.togglePause = togglePause; window.__demo.panes = panes;
  if (params.get('autostart') === '1') start();
})();
